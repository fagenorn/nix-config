# Task 4: `git -C <dir>` judged against its target repository

Spec § Accepted invocation forms › Directory option, § Canonical command, § Repository context, § Shape fixture (second bullet), § README; per D2, D7, D8, D10, D13. After this task one plain `git -C <dir>` before a push or a branch deletion is stripped to the canonical command, and a push's repository context (origin slug, `origin/HEAD`, derived-row lookup and row check, tag lookup) is built from `<dir>` joined to the payload `cwd`, one context per distinct directory under the one invocation deadline. This is the last task: its Step 4 runs the full guard suite on the final code.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `tests/fixtures/guarded-command-shapes.json`
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes: Task 1's `strip_spelling(text, spelling)`, `strip_scrub_prefix(text)`, `canonical_text(operation, text)`; Task 3's `git_invocation`, `gh_invocation`, `guarded_invocation` (2-tuples), `NOT_COMMAND_POSITION`; Task 2's `unvalidatable`; existing `Context(args, base, cwd, deadline)` (`cwd` feeds `detect_repository`, `default_branch` and `validate_tag_push`'s `cwd=context.cwd`), `INVOCATION_DEADLINE_SECONDS`; in the suite `make_repo(origin, default_branch=…)`, `tagged_repo(slug)` (annotated `v1.2.3`, origin/HEAD `main`), `run_guard(command, cwd=None)`.
- Produces: `git_invocation`, `gh_invocation`, `guarded_invocation` return `(operation, problem, directory)`; `guarded_operations(command) -> list[tuple[str, str, str | None, str | None]]` (operation, segment, problem, directory); `canonical_text(operation: str, text: str, directory: str | None) -> str`; `target_directory(directory: str | None, cwd: object) -> str | None`.

**Invariants:**
- `directory` is the `-C` value only for a recognised git invocation with no recognition problem at a command position; every other entry carries None (D6).
- `canonical_text` strips `git -C <directory> ` to `git ` only at the start of the text left after the scrub prefix, and only when a non-whitespace character follows (D13); a quoted or escaped spelling stays whole for the grammar to refuse.
- `target_directory`: no `-C` → the payload `cwd` when it is a non-empty string, else None; an absolute `-C` stands alone; a relative one is `os.path.join(cwd, directory)` with no normalisation, or None with no string `cwd` (D7). None and a missing or non-repository directory both judge as "repository unknown".
- `main` keeps a dict of contexts keyed by target directory, builds each lazily, and passes every one the same deadline `started + INVOCATION_DEADLINE_SECONDS` (D8). Branch deletion builds none.

- [ ] **Step 1: Write the failing tests**

In `tests/fixtures/guarded-command-shapes.json`, insert at the start of `invocation_shapes`:

```json
    {"id": "push.dir", "template": "git -C <repository-root> push origin <branch>",
     "label": "push", "verdict": {"exit": 0}},
    {"id": "push.env-dir", "template": "env -u GITHUB_TOKEN git -C <repository-root> push -u origin <branch>",
     "label": "push", "verdict": {"exit": 0}},
    {"id": "branch.dir", "template": "git -C <repository-root> branch -d <branch>",
     "label": "branch deletion", "verdict": {"exit": 0}},
```

In `tests/test_claude_permission_guard.py`, add directly before `test_tag_push_near_misses_are_refused`:

```python
    def test_git_dash_c_is_judged_against_its_target_repository(self):
        """Issue 400 AC2, D7, D8: `git -C <dir>` builds the push's repository context
        from <dir> joined to the payload cwd, one context per distinct directory."""
        here = self.make_repo("git@github.com:fagenorn/nix-config.git")
        there = self.make_repo("git@github.com:fagenorn/guard-fixture.git",
                               default_branch="trunk")
        foreign = self.make_repo("git@github.com:someoneelse/tool.git")
        tagged = self.tagged_repo("fagenorn/guard-fixture")
        # A repository directory whose basename is `git` (issue 400 D15).
        named = there.parent / "git"
        named.symlink_to(there)
        feature = "issue-400-topic"
        for command, cwd in (
            (f"git -C {there} push origin {feature}", here),
            (f"git -C {there} push origin main", here),
            (f"git -C {here} push origin {feature}", foreign),
            (f"git -C {there.name} push origin {feature}", there.parent),
            (f"git -C {there} push origin main; git push origin trunk", here),
            (f"git -C {tagged} push origin refs/tags/v1.2.3", here),
            (f"env -u GH_TOKEN git -C {there} push origin {feature}", here),
            (f"git -C {there.name} branch -d {feature}", None),
            (f"git -C {named} push origin {feature}", here),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        unknown = "unsafe push: repository unknown is outside standing authorization"
        grammar = "unsafe push: expected exactly git push [-u] origin <branch>"
        for command, cwd, reason in (
            (f"git -C {there} push origin trunk", here,
             "unsafe push: refusing to push the default branch trunk"),
            (f"git -C {foreign} push origin {feature}", here,
             "unsafe push: repository someoneelse/tool is outside standing authorization"),
            (f"git -C {there.name} push origin {feature}", None, unknown),
            (f"git -C {there}/missing push origin {feature}", here, unknown),
            (f"git -C {there} push origin main; git push origin main", here,
             "unsafe push: refusing to push the default branch main"),
            (f"git push origin trunk; git -C {there} push origin trunk", here,
             "unsafe push: refusing to push the default branch trunk"),
            (f"git -C {here} push origin refs/tags/v1.2.3", tagged,
             "unsafe push: v1.2.3 is not an existing annotated tag"),
            (f'git -C "{there}" push origin {feature}', here, grammar),
            (f"git -C {there}  push origin {feature}", here, grammar),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)
```

- [ ] **Step 2: Watch the tests fail**

Run: the guard-suite invocation with `-k test_every_invocation_shape_gets_its_verdict -k test_git_dash_c_is_judged_against_its_target_repository` (timeout 3600 s).
Expected: `FAILED (failures=18)`: the three new shapes, all nine allowed rows (the `named` row included: at Task 3 it is refused by the push grammar), and six refused rows (each refused by the push grammar instead of the target repository's verdict); the relative-`<dir>`-without-`cwd`, quoted and double-space rows already pass. Any other result: stop. (Planning dry-ran exactly this on a Task 3 implementation.)

- [ ] **Step 3: Implement**

In `home/common/claude-code/lifecycle_guard.py`:

a. `git_invocation`: its docstring's first line becomes "(operation, problem, directory) for a guarded git invocation, else None" (then "(issue 400 D3)."), and its last paragraph gains "`directory` is that `-C` value when `problem` is None, else None." Return `operation, None, (directories[0] if directories else None)` on success and `operation, f"{problem}; {INVOCATION_FORM_HINT}", None` on a problem. `gh_invocation` returns `found, f"gh named by a path; {INVOCATION_FORM_HINT}", None` and `found, None, None`, its docstring's first line "(operation, problem, None) for a guarded gh invocation, else None (issue 400 D4)." `guarded_invocation`'s docstring begins "(operation, problem, directory) when the word at `index` starts a guarded git or gh invocation".

b. `guarded_operations`: every entry becomes a 4-tuple. Its docstring's first sentence becomes "(operation, segment, problem, directory) for every guarded verb the shell would run. `directory` is the accepted `git -C` value, else None." `unvalidatable` builds `(operation, segment, reason, None)` and `("label", segment, reason, None)`; the two `found.append(("label", command, …))` calls at the end gain a trailing `None`; and the invocation loop body becomes:

```python
            operation, problem, directory = invocation
            if not flags[index]:
                problem, directory = NOT_COMMAND_POSITION, None
            found.append((operation, segment, problem, directory))
```

c. Replace `canonical_text` and add `target_directory` after it:

```python
def canonical_text(operation, text, directory):
    """The text `operation`'s grammar judges (issue 400 D13).

    Push and PR creation are judged per segment, with leading whitespace dropped;
    every verb but branch deletion (D2) then loses an exact scrub prefix; and,
    with a `git -C` `directory`, a leading `git -C <directory> ` becomes `git `.
    Text in any other spelling is returned whole, for the grammar to refuse.
    """
    if operation in ("push", "pr-create"):
        text = text.lstrip()
    if operation != "branch":
        text = strip_scrub_prefix(text)
    if directory is not None:
        rest = strip_spelling(text, f"git -C {directory} ")
        if rest is not None:
            text = "git " + rest
    return text


def target_directory(directory, cwd):
    """The directory a push's repository context is built from (issue 400 D7).

    The `git -C` `directory` joined to the payload `cwd` (an absolute one stands
    alone; no normalisation, so git resolves it as the shell's `git -C` would),
    or `cwd` with no `-C`. None when there is none to use: a relative
    `directory` with no string `cwd`, or no `-C` and no string `cwd`.
    """
    base = cwd if isinstance(cwd, str) and cwd else None
    if directory is None:
        return base
    if os.path.isabs(directory):
        return directory
    if base is None:
        return None
    return os.path.join(base, directory)
```

d. Replace the `Context` docstring with:

```python
    """Injected dependencies plus one target directory's repository facts,
    resolved once per directory (issue 400 D8).

    `cwd` is that directory: the payload `cwd`, or a push's `git -C` directory
    (`target_directory`). Building a context is the one place the compiled
    policy is opened and the one place the row check runs, so a command with no
    push, PR creation, merge or release creation never reads the first or
    starts the second.
    """
```

e. `main`: the label loop unpacks `for operation, _segment, problem, _directory in operations:`. Replace `context = None` and the loop header with:

```python
    # One context per distinct target directory, all under one deadline.
    contexts = {}
    for operation, segment, problem, directory in operations:
```

call `canonical_text(operation, judged, directory)`, and replace the `if context is None: …` block with:

```python
                target = target_directory(directory, payload.get("cwd"))
                context = contexts.get(target)
                if context is None:
                    context = contexts[target] = Context(
                        args, base, target,
                        started + INVOCATION_DEADLINE_SECONDS,
                    )
```

In `home/common/claude-code/README.md`, `## Adjudicated verbs`, first paragraph: insert before "The merge's own `gh` lookups run with" the sentence: "`git push` and `git branch -d` also take one `git -C <dir>` directly after `git` (issue 400), `<dir>` one unquoted word without whitespace, quotes or shell-active characters, a relative one joined to the payload `cwd` without normalisation: the guard strips it to the canonical command and builds a push's repository context — origin slug, `origin/HEAD`, the derived-row lookup and row check, and the tag lookup — from that directory, one context per distinct directory in a command under the one invocation deadline, while branch deletion checks only its spelling; an unresolvable directory is an unknown repository, refused as outside standing authorization." Second paragraph: change "(the base policy `git`, the payload `cwd`)" to "(the base policy `git`, in the push's target directory: its `git -C` directory, else the payload `cwd`)". In `## Guard policy`, **Row check.** paragraph (Phase-5 R3): replace "The check runs once per invocation, when the context is built," with "The check runs once per repository context, when that context is built (a command whose pushes name several `git -C` directories builds one context per distinct directory, all under the one invocation deadline),".

- [ ] **Step 4: Verify**

Run: the guard-suite invocation (full suite, timeout 3600 s).
Expected: `OK`, every test of the suite, the adversarial table included.

Run: the shell-example run.
Expected: `OK` (one skip).

Run (content gate, timeout 60 s):

```bash
set -e
if grep -n 'context = None' home/common/claude-code/lifecycle_guard.py; then exit 1; fi
grep -q 'contexts\[target\] = Context(' home/common/claude-code/lifecycle_guard.py
```

Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py tests/fixtures/guarded-command-shapes.json home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(guard): accept git -C <dir> and judge it against the target repository"
```
