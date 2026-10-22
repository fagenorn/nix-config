# Task 3: git and gh invocation recognition

Spec § Recognition (git, gh, Where), § Accepted invocation forms › Refusals judged at recognition, § Shape fixture (second bullet), § README; per D3, D4, D6, D10. After this task a word whose basename is `git` or `gh` starts an invocation that is adjudicated whatever global options, flags or program path sit around its verb, and every unaccepted form is refused before any repository lookup. A single plain `git -C <dir>` is recognised here but not yet stripped, so its push or branch deletion is refused by the grammar until Task 4.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `tests/fixtures/guarded-command-shapes.json`
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes: Task 2's `GUARDED_VERBS`, `program_name(word)`, `command_position_flags(tokens) -> (flags, split_string)`, `EVALUATOR_REASON`, `SPLIT_STRING_REASON`, the `invocation_shapes` fixture section and `test_every_invocation_shape_gets_its_verdict`; existing `UNSAFE_BRANCH_CHARS`.
- Produces: `NOT_COMMAND_POSITION: str`, `INVOCATION_FORM_HINT: str`; `git_directory_problem(directory: str) -> bool`; `git_invocation(program: str, words: list[str]) -> tuple[str, str | None] | None`; `gh_invocation(program: str, words: list[str]) -> tuple[str, str | None] | None`; `guarded_invocation(tokens, index) -> tuple[str, str | None] | None` (operation, problem). Task 4 widens all three tuples with a directory.

**Invariants:**
- `guarded_invocation` reads the words after the program word up to the next operator token, and dispatches on `program_name` of the word at `index`; any other word yields None.
- git (D3): leading words that begin with `-` are global options, each exact `-C` taking the next word as its directory. With no other option and at most one `-C`, only the first word after them is the subcommand (`push`, or `branch` followed by `-d`); otherwise `push`, or `branch` followed by `-d`, anywhere among the words counts.
- gh (D4): guarded when the first two words are a guarded path; otherwise when, after the first occurrence of the path's first word, some occurrence of its second word has a flag word (begins with `-`) anywhere before it. The guarded set never grows.
- Refusal order for a guarded invocation (D6): program named by a path, then the first foreign git global option, then a repeated `-C`, then a `-C` directory that is empty or holds whitespace, a quote or an `UNSAFE_BRANCH_CHARS` character. Each reason ends `; run git and gh by name, and carry a directory only as git -C <dir>`. A gh flag between path words gets no recognition refusal.
- At a non-command position every recognised invocation gets `NOT_COMMAND_POSITION`, whatever its recognition problem.

- [ ] **Step 1: Write the failing tests**

In `tests/fixtures/guarded-command-shapes.json`, append to `invocation_shapes`:

```json
    {"id": "push.config-option", "template": "git -c core.hooksPath=/dev/null push origin <branch>",
     "label": "push", "verdict": {"exit": 2, "reason": "git -C <dir>"}},
    {"id": "push.git-dir", "template": "git --git-dir=<repository-root>/.git push origin <branch>",
     "label": "push", "verdict": {"exit": 2, "reason": "git -C <dir>"}},
    {"id": "push.second-dir", "template": "git -C <repository-root> -C <repository-root> push origin <branch>",
     "label": "push", "verdict": {"exit": 2, "reason": "git -C <dir>"}},
    {"id": "push.path-git", "template": "/usr/bin/git push origin <branch>",
     "label": "push", "verdict": {"exit": 2, "reason": "git -C <dir>"}},
    {"id": "merge.path-gh", "template": "/usr/local/bin/gh pr merge <pr-num> --repo <resolved-repository> --merge --delete-branch",
     "label": "merge", "verdict": {"exit": 2, "reason": "git -C <dir>"}},
    {"id": "merge.flag-before-path", "template": "gh --repo <resolved-repository> pr merge <pr-num> --merge --delete-branch",
     "label": "merge", "verdict": {"exit": 2, "reason": "does not match the guarded merge grammar"}},
    {"id": "merge.flag-between-path", "template": "gh pr --repo <resolved-repository> merge <pr-num> --merge --delete-branch",
     "label": "merge", "verdict": {"exit": 2, "reason": "does not match the guarded merge grammar"}}
```

In `tests/test_claude_permission_guard.py`, add directly before `test_tag_push_near_misses_are_refused`:

```python
    def test_recognition_reads_through_global_options_and_paths(self):
        """Issue 400 AC3, D3, D4, D6: a guarded verb behind git global options, gh
        flags or a program path is adjudicated; unguarded invocations still pass."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        spelling = ("the git -C directory must be one word without whitespace, "
                    "quotes or shell-active characters")
        hint = "; run git and gh by name, and carry a directory only as git -C <dir>"
        for command, label, reason in (
            ("git -C 'two words' push origin issue-400-topic", "push", spelling + hint),
            ("git -C ~/worktree push origin issue-400-topic", "push", spelling + hint),
            ("git -C /tmp/x -c a=b push origin issue-400-topic", "push",
             "git global option -c is not accepted" + hint),
            ("git --no-pager branch -d issue-400-topic", "branch deletion",
             "git global option --no-pager is not accepted" + hint),
            ("/usr/bin/git branch -d issue-400-topic", "branch deletion",
             "git named by a path" + hint),
            ("/opt/homebrew/bin/gh release create v1.2.3 --repo fagenorn/nix-config "
             '--verify-tag --title "t" --notes-file /tmp/n.md', "release creation",
             "gh named by a path" + hint),
            ("gh -R fagenorn/nix-config pr create --repo fagenorn/nix-config --base main "
             '--head t --title "x" --body "y"', "PR creation",
             "expected exactly gh pr create"),
            ("xargs git -C /tmp/x push origin issue-400-topic", "push",
             "the verb is not in a command position"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: {reason}", result.stderr)
        for command in (
            "git -C /tmp status --short",
            "git -C /tmp/x log --grep push",
            "git --no-pager log --oneline",
            "git -c core.pager=cat diff",
            "/usr/bin/git status",
            "gh pr view 1 --json mergeable",
            "gh pr list --state merged",
            "gh -R fagenorn/nix-config pr view 1",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))
```

- [ ] **Step 2: Watch the tests fail**

Run: the guard-suite invocation with `-k test_every_invocation_shape_gets_its_verdict -k test_recognition_reads_through_global_options_and_paths` (timeout 3600 s).
Expected: `FAILED (failures=15)`: the seven new shapes (each runs unadjudicated and exits 0) and the eight refused rows of the recognition test; Task 2's four shapes and the eight passing rows pass. Any other result: stop. (Planning dry-ran exactly this on a Task 2 implementation.)

- [ ] **Step 3: Implement**

In `home/common/claude-code/lifecycle_guard.py`:

a. After `SPLIT_STRING_REASON` add:

```python
NOT_COMMAND_POSITION = (
    "the verb is not in a command position the guard can validate; quote it "
    "if you only mean to mention it"
)
# Ends every refusal of an invocation form at recognition (issue 400 D6).
INVOCATION_FORM_HINT = "run git and gh by name, and carry a directory only as git -C <dir>"
```

b. Add directly before `unvalidatable` (the algorithm is the decision, per D3, D4 and D6):

```python
def git_directory_problem(directory):
    """True when a `git -C` directory is not one plain word: empty, or holding
    whitespace, a quote or a shell-active character (issue 400 D7)."""
    return not directory or any(
        character.isspace() or character in "'\"" or character in UNSAFE_BRANCH_CHARS
        for character in directory
    )


def git_invocation(program, words):
    """(operation, problem) for a guarded git invocation, else None (issue 400 D3).

    `words` follow the `git` word up to the end of its simple command. Leading
    words that begin with `-` are global options, each `-C` taking the next word
    as its directory. With no other option and at most one `-C`, the next word is
    the subcommand; otherwise `push`, or `branch` then `-d`, anywhere among
    `words` counts, since the walk cannot know which options take a value.
    `problem` is None for a plain `git` with no global option or one plain
    `-C <dir>`, else the recognition refusal (D6).
    """
    options = []
    directories = []
    index = 0
    while index < len(words) and words[index].startswith("-"):
        if words[index] == "-C" and index + 1 < len(words):
            directories.append(words[index + 1])
            index += 2
        else:
            options.append(words[index])
            index += 1
    if not options and len(directories) <= 1:
        candidates = [words[index:index + 2]]
    else:
        candidates = [words[position:position + 2] for position in range(len(words))]
    operation = None
    for candidate in candidates:
        if candidate[:1] == ["push"]:
            operation = "push"
        elif candidate == ["branch", "-d"]:
            operation = "branch"
        if operation is not None:
            break
    if operation is None:
        return None
    if program != "git":
        problem = "git named by a path"
    elif options:
        problem = f"git global option {options[0]} is not accepted"
    elif len(directories) > 1:
        problem = "git -C given more than once"
    elif directories and git_directory_problem(directories[0]):
        problem = (
            "the git -C directory must be one word without whitespace, quotes "
            "or shell-active characters"
        )
    else:
        return operation, None
    return operation, f"{problem}; {INVOCATION_FORM_HINT}"


def gh_invocation(program, words):
    """(operation, problem) for a guarded gh invocation, else None (issue 400 D4).

    Guarded when `words` begin with a guarded path (`pr merge`, `pr create`,
    `release create`, `release new`), or when a flag word comes before an
    occurrence of the path's second word that follows its first. Flags after
    the path never matter. A gh named by a path is refused (D6); a flag between
    the path words is left to the verb's grammar.
    """
    paths = [
        (list(verb_words[1:]), operation)
        for verb_words, operation in GUARDED_VERBS
        if verb_words[0] == "gh"
    ]
    found = next((operation for path, operation in paths if words[:2] == path), None)
    for (first, second), operation in paths:
        if found is not None:
            break
        if first not in words:
            continue
        start = words.index(first) + 1
        if any(
            words[position] == second
            and any(word.startswith("-") for word in words[:position])
            for position in range(start, len(words))
        ):
            found = operation
    if found is None:
        return None
    if program != "gh":
        return found, f"gh named by a path; {INVOCATION_FORM_HINT}"
    return found, None


def guarded_invocation(tokens, index):
    """(operation, problem) when the word at `index` starts a guarded git or gh
    invocation, matched by basename, else None.

    Its words run to the next operator token. `problem` is a recognition refusal
    or None; the caller still judges the command position.
    """
    value, operator = tokens[index]
    if operator:
        return None
    words = []
    for word, word_is_operator in tokens[index + 1:]:
        if word_is_operator:
            break
        words.append(word)
    name = program_name(value)
    if name == "git":
        return git_invocation(value, words)
    if name == "gh":
        return gh_invocation(value, words)
    return None
```

c. In `guarded_operations`, replace the whole contiguous-match loop (`for index in range(len(values)):` through its `break`) with:

```python
        for index in range(len(tokens)):
            invocation = guarded_invocation(tokens, index)
            if invocation is None:
                continue
            operation, problem = invocation
            found.append((
                operation, segment, problem if flags[index] else NOT_COMMAND_POSITION,
            ))
```

In `home/common/claude-code/README.md`, `## Allow surface and lifecycle guard`: after "so `git  push`, `git<TAB>push` and `"git" push` all count." insert: "A word whose basename is `git` starts a git invocation: with no global option, or one `-C <dir>`, the word after them is its subcommand (`push`, or `branch` then `-d`), and with any other global option a `push` or `branch -d` anywhere among its words counts; a word whose basename is `gh` counts when its first two words are `pr merge`, `pr create`, `release create` or `release new`, or when a flag comes before the path's second word and both path words occur in order, so `gh --repo a/b pr merge 1` counts and `gh pr view 1 --json mergeable` does not (issue 400). Such an invocation is refused before any repository lookup, the reason ending `run git and gh by name, and carry a directory only as git -C <dir>`, when its program is named by a path, or it carries a git global option other than one `-C`, a repeated `-C`, or a `-C` directory holding whitespace, a quote or a shell-active character; a gh flag between the path words is left to the verb's grammar."

- [ ] **Step 4: Verify**

Run: the guard-suite invocation (full suite, timeout 3600 s).
Expected: `OK`, the adversarial table and the forge-adapter rows included.

Run: the shell-example run.
Expected: `OK` (one skip).

Run (content gate, timeout 60 s):

```bash
set -e
if grep -n 'values\[index:index + len(verb_words)\]' home/common/claude-code/lifecycle_guard.py; then exit 1; fi
test "$(grep -c '"git -C <dir>"' tests/fixtures/guarded-command-shapes.json)" = 5
```

Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py tests/fixtures/guarded-command-shapes.json home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(guard): recognise git and gh verbs behind global options, flags and paths"
```
