# Task 1: Wrapper option arguments and the credential-scrub prefix

Spec § Recognition › Where (wrapper option arguments), § Accepted invocation forms › Scrub prefix, § Canonical command, § Shape fixture (first bullet), § README; per D1, D2, D9, D10, D13. After this task the verb pass finds the wrapped program behind `env -u NAME`/`sudo -u user`, the scrub prefix in either spelling reaches every verb's grammar except branch deletion, and every other wrapper reaches the grammar and is refused there.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `tests/fixtures/guarded-command-shapes.json`
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes (existing, unchanged): `wrapper_option(wrapper, option) -> (kind, attached)` (`kind` None, `"argument"` or `"payload"`), `WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT`, `WRAPPER_OPTIONS_WITH_ARGUMENT`, `GH_ENV_TOKEN_NAMES`, `validate_push(segment, context)`, `validate_pr_create(segment, context)`, `validate_merge(command, context)`, `validate_release(command, context)`, `validate_branch_delete(command, git_bin, timeout)`; in the suite `make_repo`, `run_guard`, `SHAPES`, `shape_command`, `assert_shape_verdict`.
- Produces: `SCRUB_PREFIXES: tuple[str, ...]`; `strip_spelling(text: str, spelling: str) -> str | None`; `strip_scrub_prefix(text: str) -> str`; `canonical_text(operation: str, text: str) -> str` (Task 4 adds a `directory` parameter); `command_position_flags(tokens) -> list[bool]` now consuming wrapper option arguments (Task 2 changes its return value); fixture key `env_prefixed` on every `skill_forms` row; suite constant `ENV_TOKEN_PREFIX`.

**Invariants:**
- `SCRUB_PREFIXES` holds exactly `unset N && `, `unset N M && `, `env -u N `, `env -u N -u M ` for distinct `N`, `M` in `GH_ENV_TOKEN_NAMES` (8 spellings), longest first, and contains `UNSET_GITHUB_TOKEN_PREFIX`.
- A prefix or spelling is stripped only from the very start of the judged text, and only when the character after it exists and is not whitespace (D13).
- Branch deletion is never stripped of a scrub prefix (D2).
- No validator strips anything; `main` passes each validator the output of `canonical_text`.
- A wrapper option word that takes an argument consumes the next word unless the argument is attached; an operator token clears a pending argument.

- [ ] **Step 1: Write the failing tests**

In `tests/fixtures/guarded-command-shapes.json`, give every `skill_forms` row an `"env_prefixed"` member directly after `"prefixed"` (D10): `{"exit": 0}` for `push.first`, `push.later`, `merge.subject` and `merge.plain`; `{"exit": 2, "reason": "expected exactly git branch -d <branch>"}` for `branch.local`; `{"exit": 2, "reason": "expected exactly git push [-u] origin <branch>"}` for `branch.remote`. Delete the `refused_shapes` rows `push.env-wrapper` and `merge.env-wrapper`: the new verdicts are their home.

In `tests/test_claude_permission_guard.py`:

1. In `test_prefixed_merge_near_misses_fail_closed`, delete the row `f"unset GITHUB_TOKEN GH_TOKEN && {merge}",              # extra variable` (D1 accepts it; the new test pins it).
2. After `TOKEN_PREFIX = "unset GITHUB_TOKEN && "` add `ENV_TOKEN_PREFIX = "env -u GITHUB_TOKEN "`, and in `test_every_guarded_command_shape_gets_its_verdict` replace the variant tuple with:

```python
            for variant, text in (("bare", command), ("prefixed", self.TOKEN_PREFIX + command),
                                  ("env_prefixed", self.ENV_TOKEN_PREFIX + command)):
```

3. Add directly before `test_merge_lookups_drop_env_github_tokens`:

```python
    def test_credential_scrub_prefix_forms_and_wrapper_near_misses(self):
        """Issue 400 AC1, D1, D13: either scrub-prefix spelling reaches every verb's
        grammar; any other wrapper reaches the grammar too and is refused there."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        push = "git push origin issue-400-topic"
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge --delete-branch"
        create = ('gh pr create --repo fagenorn/nix-config --base main '
                  '--head issue-400-topic --title "x" --body "y"')
        release = ('gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag '
                   '--title "v1.2.3" --notes-file /tmp/n.md')
        for command in (
            f"env -u GITHUB_TOKEN {push}",
            "unset GH_TOKEN && git push -u origin issue-400-topic",
            f"env -u GITHUB_TOKEN {merge}",
            f"env -u GH_TOKEN {merge}",
            f"env -u GITHUB_TOKEN -u GH_TOKEN {merge}",
            f"unset GITHUB_TOKEN GH_TOKEN && {merge}",
            f"unset GH_TOKEN GITHUB_TOKEN && {merge}",
            f"env -u GH_TOKEN -u GITHUB_TOKEN {push}",
            f"true && env -u GH_TOKEN {push}",
            f"env -u GITHUB_TOKEN {create}",
            f"env -u GITHUB_TOKEN {release}",
            f"unset GH_TOKEN && {release}",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        push_grammar = "unsafe push: expected exactly git push [-u] origin <branch>"
        merge_grammar = "unsafe merge: command does not match the guarded merge grammar"
        for command, reason in (
            (f"env -u PATH {push}", push_grammar),
            (f"env FOO=1 {push}", push_grammar),
            (f"env -i {push}", push_grammar),
            (f"env -u GITHUB_TOKEN -i {push}", push_grammar),
            (f"env --unset=GITHUB_TOKEN {push}", push_grammar),
            (f"sudo -u x {push}", push_grammar),
            (f"env -u GITHUB_TOKEN -u GITHUB_TOKEN {push}", push_grammar),   # repeated name
            (f"env -uGITHUB_TOKEN {push}", push_grammar),                    # attached
            (f"env -u GITHUB_TOKEN -- {push}", push_grammar),
            (f"env env -u GITHUB_TOKEN {push}", push_grammar),               # second env
            (f"env -u GITHUB_TOKEN env {push}", push_grammar),
            (f"env -u GITHUB_TOKEN  {push}", push_grammar),                  # double space
            (f"env -u GITHUB_TOKEN {merge}; echo x", merge_grammar),
            (f"env -u GITHUB_TOKEN -u GITHUB_TOKEN {merge}", merge_grammar),
            (f"unset GITHUB_TOKEN GITHUB_TOKEN && {merge}", merge_grammar),
            (f"env  -u GITHUB_TOKEN {merge}", merge_grammar),
            (f"env -u GITHUB_TOKEN  {merge}", merge_grammar),
            ("env -u GITHUB_TOKEN git branch -d issue-400-topic",
             "unsafe branch deletion: expected exactly git branch -d <branch>"),
            ("unset GITHUB_TOKEN && git branch -d issue-400-topic",
             "unsafe branch deletion: forbidden raw command character"),
            # The wrapper's option argument is consumed, so `sh` is the command word.
            ("sudo -u root sh -c 'git push origin issue-400-topic'",
             "unsafe push: shell source passed to an evaluator cannot be validated"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)
```

- [ ] **Step 2: Watch the tests fail against the unchanged guard**

Run: the guard-suite invocation with `-k test_credential_scrub_prefix_forms_and_wrapper_near_misses -k test_every_guarded_command_shape_gets_its_verdict -k test_prefixed_merge_near_misses_fail_closed` (timeout 3600 s).
Expected: `FAILED (failures=31)`: 25 subtests of the new test (every allowed row but `unset GH_TOKEN && git push -u …`, which passes today; every refused row but `env FOO=1`, `env -i`, `env --unset=`, `env -uGITHUB_TOKEN`, `unset GITHUB_TOKEN GITHUB_TOKEN && …` and the `unset … && git branch -d` row, which already carry the expected reason) and the six `env_prefixed` subtests of the shape test; the near-miss test passes. Any other result means the tests do not pin this change; stop. (Planning dry-ran exactly this at `64337002`.)

- [ ] **Step 3: Implement**

In `home/common/claude-code/lifecycle_guard.py`:

a. Replace the four comment lines above `UNSET_GITHUB_TOKEN_PREFIX` (they begin "A resolved exhaustive credential-name list") and add `SCRUB_PREFIXES` after the assignment, which stays as it is:

```python
# The scrub-prefix spelling a resolved exhaustive credential-name list yields
# (`unset GITHUB_TOKEN && gh ...`), and the one the ship-issue skill check reads
# from this single assignment. SCRUB_PREFIXES below includes it.
UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "
# Every accepted credential-scrub prefix (issue 400 D1): `unset N && `,
# `unset N M && `, `env -u N ` and `env -u N -u M `, single spaces, with N and M
# distinct members of GH_ENV_TOKEN_NAMES. Unsetting any other name could change
# the repository or config the command sees. Longest first, so a two-name
# spelling is tried before the one-name spelling it begins with.
SCRUB_PREFIXES = tuple(sorted(
    {
        spelling
        for names in [(name,) for name in GH_ENV_TOKEN_NAMES] + [
            (first, second)
            for first in GH_ENV_TOKEN_NAMES for second in GH_ENV_TOKEN_NAMES
            if first != second
        ]
        for spelling in (
            "unset " + " ".join(names) + " && ",
            "env " + " ".join(f"-u {name}" for name in names) + " ",
        )
    },
    key=lambda spelling: (-len(spelling), spelling),
))
```

b. Replace `command_position_flags` with:

```python
def command_position_flags(tokens):
    """Per token: does a simple command start here?

    Keywords, assignments and wrappers keep the position open. A wrapper option
    that takes an argument (`env -u NAME`, `sudo -u user`, per the wrapper option
    tables) also consumes the next word, unless the argument is attached
    (`-uNAME`, `--user=anis`), so the wrapped program is the command word. An
    operator token ends any pending option argument.
    """
    flags = [False] * len(tokens)
    open_position = True
    wrapper = None
    pending = 0
    for index, (value, operator) in enumerate(tokens):
        if operator:
            open_position, wrapper, pending = True, None, 0
            continue
        if not open_position:
            continue
        if pending:
            pending -= 1
            continue
        if ASSIGNMENT_PREFIX.match(value) is not None:
            continue
        if value in COMMAND_KEYWORDS or value in COMMAND_WRAPPERS:
            wrapper = value
            continue
        if wrapper is not None and value.startswith("-"):
            kind, attached = wrapper_option(wrapper, value)
            if kind is not None and attached is None:
                pending += 1
            continue
        flags[index] = True
        open_position = False
    return flags
```

c. In the comment above `WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT`, change "Used only by the detaching pass." to "Used by the verb pass and the detaching pass." In the `detaching_command_flags` docstring replace the sentences from "Like `command_position_flags`, but it also steps over redirections" through "hence the extra stepping." with: "Like `command_position_flags`, which also steps over the arguments of wrapper options (`sudo -u anis nohup x`), but it also steps over redirections, attached (`nohup>log`) or not, so `>log nohup x` is seen. An operator token ends any pending option argument. The verb pass keeps `command_position_flags`; this pass has no such fail-closed backstop, hence the extra stepping."

d. Add directly before `detect_repository`:

```python
def strip_spelling(text, spelling):
    """The rest of `text` after a leading `spelling`, or None.

    None also when the rest is empty or begins with whitespace: a doubled space
    is not the spelling (issue 400 D13).
    """
    if not text.startswith(spelling):
        return None
    rest = text[len(spelling):]
    if not rest or rest[0].isspace():
        return None
    return rest


def strip_scrub_prefix(text):
    """`text` without its leading credential-scrub prefix, else `text` unchanged."""
    for prefix in SCRUB_PREFIXES:
        rest = strip_spelling(text, prefix)
        if rest is not None:
            return rest
    return text


def canonical_text(operation, text):
    """The text `operation`'s grammar judges (issue 400 D13).

    Push and PR creation are judged per segment, with leading whitespace dropped;
    every verb but branch deletion (D2) then loses an exact scrub prefix. Text
    in any other spelling is returned whole, for the grammar to refuse.
    """
    if operation in ("push", "pr-create"):
        text = text.lstrip()
    if operation != "branch":
        text = strip_scrub_prefix(text)
    return text
```

e. In `validate_release`, delete the two lines that strip `UNSET_GITHUB_TOKEN_PREFIX` and change the docstring to "Release creation is judged on the whole canonical command, like the merge." In `validate_merge`, replace the five comment lines beginning "The one sanctioned prefix" and the two strip lines after them with:

```python
    # `command` is the whole canonical command, its scrub prefix already
    # stripped, so the merge still tolerates no other chaining.
```

f. In `main`, inside the `try:` of the operations loop, replace the branch-deletion comment and the dispatch with:

```python
            # Push and PR creation are judged per segment; the other verbs on the
            # whole command, so they tolerate no chaining.
            judged = segment if operation in ("push", "pr-create") else command
            text = canonical_text(operation, judged)
            if operation == "branch":
                # Branch deletion is judged in every repository: it needs no
                # forge state.
                status = validate_branch_delete(
                    text, args.git_bin, args.child_timeout_seconds
                )
            else:
                if context is None:
                    context = Context(
                        args, base, payload.get("cwd"),
                        started + INVOCATION_DEADLINE_SECONDS,
                    )
                if operation == "push":
                    status = validate_push(text, context)
                elif operation == "pr-create":
                    status = validate_pr_create(text, context)
                elif operation == "release":
                    status = validate_release(text, context)
                else:
                    status = validate_merge(text, context)
```

In `home/common/claude-code/README.md`:
- `## Allow surface and lifecycle guard`: change "and behind `command`/`env`/`sudo`-style wrappers —" to "and behind `command`/`env`/`sudo`-style wrappers, stepping over their option arguments (`env -u NAME`, `sudo -u user`, attached and long forms included) —".
- `## Adjudicated verbs`, first paragraph: replace the clause from "optionally behind the exact literal prefix" through "so nothing else can chain);" with: "optionally behind a credential-scrub prefix (issue 400), spelled exactly `unset N && `, `unset N M && `, `env -u N ` or `env -u N -u M ` with single spaces and `N`, `M` distinct members of the credential-name set `GITHUB_TOKEN`, `GH_TOKEN` (`unset GITHUB_TOKEN && ` is the spelling derived from `bindings.tracker.credential_env.unset_before_invocation`'s exhaustive credential-name list), stripped from the start of the whole command so the remainder is still judged whole and nothing else can chain; `git push` and `gh pr create` take the `env -u` spellings at the start of their own segment (the `unset` spelling is an earlier segment there), `git branch -d` takes none, and any other `env` option or assignment, `--`, `--unset=` or attached `-uN` spelling, repeated name or doubled space leaves the text whole for the grammar to refuse;".
- Second paragraph: change "behind the same optional `unset GITHUB_TOKEN && ` prefix" to "behind the same optional credential-scrub prefix", and in the shape-fixture sentence change "each with the guard's verdict;" to "each with the guard's verdict bare, behind `unset GITHUB_TOKEN && ` and behind `env -u GITHUB_TOKEN `;".

- [ ] **Step 4: Verify**

Run: the guard-suite invocation (full suite, timeout 3600 s).
Expected: `OK`, the adversarial table included.

Run: the shell-example run.
Expected: `OK` (one skip).

Run (content gate, timeout 60 s):

```bash
set -e
test "$(grep -c '^UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "$' home/common/claude-code/lifecycle_guard.py)" = 1
if grep -n 'startswith(UNSET_GITHUB_TOKEN_PREFIX)' home/common/claude-code/lifecycle_guard.py; then exit 1; fi
if grep -n 'env-wrapper' tests/fixtures/guarded-command-shapes.json; then exit 1; fi
```

Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py tests/fixtures/guarded-command-shapes.json home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(guard): step over wrapper option arguments and accept the credential-scrub prefix"
```
