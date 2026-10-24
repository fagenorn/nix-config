# Task 3: Refusals name the first problem

Spec § Problems the guard names (steps 1–8, slot problems, merge arms), § Shape fixture (second bullet), § Test seams (Adversarial table items 2 and 4); per D4, D5, D9, D16, D17. After this task a text refusal names the first problem that applies instead of a generic grammar miss, slot problems carry their value, and the merge arms name the missing `--delete-branch`. Verdicts, the accepted-forms clause and every state refusal stay exactly as Task 2 left them.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `tests/fixtures/guarded-command-shapes.json`

**Interfaces:**
- Consumes: Task 1's `walk_form(elements, words, flags) -> FormWalk`, `Literal`, `Slot`, `CompiledOperation` (`program`, `flags`, `quoted_value_flags`, `whole_text_characters`, `exact_spelling`, `scrub_prefix`, `forms`), `HEAD_COMMIT`, `form_problem(operation, compiled, text)`'s signature; Task 2's `refuse`, `accepted_forms`, `declared_integration`, `BRANCH_VALIDATION_TIMEOUT` and the suite's `refusal_line(result)`, `PREFIX_CLAUSE`, `HEAD_SHA`; base `OPERATION_LABELS`, `UNSAFE_BRANCH_CHARS`, `UNSAFE_TEXT_CHARS`, `REF_NAMESPACE_COMPONENTS`, `SEMVER_TAG`.
- Produces: `form_problem`'s new body and the helpers `shown_character(character) -> str`, `forbidden_character(text, anywhere) -> str | None`, `doubled_space_before(text, program) -> bool`, `element_spelling(element) -> str`, `structure_problem(compiled, words) -> str | None`; constant `ADVISED_CHARACTERS = frozenset(";&|<>\n")`; the problem texts in Step 3b.

**Invariants:**
- Naming runs only after `match_form` or a slot check has refused, so it changes no verdict, no clause and no state refusal (D4).
- Precedence (D4 with D16): scrub-prefix attempt, forbidden character, quoting, wrapper, leftover git global option, unknown flag, structure, exact spelling, then `does not match an accepted form`; slot problems in Task 1's slot order; then the merge arms. Ownership stays first in the four repository-bound validators.
- Step 1 reads the `shlex` words before the first word equal to the operation's program word, and applies when the first of them is `unset`, `env` or begins with `-` (what an accepted prefix stripped from a longer `env` spelling leaves, D16).
- Step 2 scans the whole text for push and branch deletion and only outside single and double quotes for the other three (D5); the first character in `UNSAFE_BRANCH_CHARS` is named, a non-printing one by its escape (`\n`); `;`, `&`, `|`, `<`, `>` and a newline add the run-alone advice.
- Step 3 keeps today's `invalid command quoting: <error>` and gets no row (D17).
- Step 7 reads the furthest walk over the program word onwards, ties to table order (D16).

- [ ] **Step 1: Write the failing tests**

1. In `tests/test_claude_permission_guard.py`, add directly after `test_state_refusals_print_no_accepted_forms`:

```python
    def test_the_retro_commands_name_their_problem_and_cure(self):
        """Issue 402 AC2: the #2342 merge names the missing --delete-branch and prints
        the feature form, which, filled in, passes; the #2268 push segment names `>`."""
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []}),
            "FAKE_PROTECTION_MODE": "nonzero"}
        merge = f"gh pr merge 2342 --repo {NODO} --merge --match-head-commit {self.HEAD_SHA}"
        line = self.refusal_line(self.run_guard(merge, cwd=nodo, env=feature_into_dev))
        self.assertEqual(
            "lifecycle guard: unsafe merge: missing --delete-branch: it may be omitted only "
            "when merging dev into main; this PR merges issue-2342-topic into dev; accepted: "
            f'gh pr merge <n> --repo {NODO} --merge [--subject "<subject>"] '
            "[--match-head-commit <sha>] --delete-branch" + self.PREFIX_CLAUSE, line)
        filled = self.run_guard(merge + " --delete-branch", cwd=nodo, env=feature_into_dev)
        self.assertEqual(0, filled.returncode, filled.stderr)
        line = self.refusal_line(self.run_guard(
            "unset GITHUB_TOKEN; git push -q origin HEAD:issue-402-topic 2>&1 | tail -2",
            cwd=repo))
        self.assertEqual(
            "lifecycle guard: unsafe push: forbidden character `>`: run the push as its own "
            "Bash call and read its output with a follow-up call; accepted: git push origin "
            "refs/tags/<vX.Y.Z>; or git push [-u] origin <branch>" + self.PREFIX_CLAUSE, line)

    def test_refusals_name_the_first_problem(self):
        """Issue 402 D4, D5, D16: one row per named problem class, each followed by the
        accepted forms; the first problem that applies is the one named."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        sha = self.HEAD_SHA
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge"
        create = "gh pr create --repo fagenorn/nix-config --base"
        release = ("gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag "
                   '--title "v1.2.3" --notes-file')
        alone = "run the {} as its own Bash call and read its output with a follow-up call"
        for command, label, problem in (
            # 1. A credential-scrub prefix attempt.
            ("env -u PATH git push origin issue-402-topic", "push",
             "unaccepted credential-scrub prefix `env -u PATH`"),
            (f"env  -u GITHUB_TOKEN {merge} --delete-branch", "merge",
             "unaccepted credential-scrub prefix `env -u GITHUB_TOKEN` (doubled space)"),
            ("env -u GITHUB_TOKEN -i git push origin issue-402-topic", "push",
             "unaccepted credential-scrub prefix `-i`"),
            ("env -u GITHUB_TOKEN git branch -d issue-402-topic", "branch deletion",
             "branch deletion takes no credential-scrub prefix"),
            # 2. A forbidden character, shown itself.
            ("git push origin $(printf issue-402-topic)", "push", "forbidden character `$`"),
            ("git branch -d issue-402-topic\ntrue", "branch deletion",
             "forbidden character `\\n`: " + alone.format("branch deletion")),
            (f"{merge} --delete-branch | cat", "merge",
             "forbidden character `|`: " + alone.format("merge")),
            # 4. A wrapper.
            ("sudo -u x git push origin issue-402-topic", "push",
             "unaccepted wrapper `sudo -u x`"),
            ("command git branch -d issue-402-topic", "branch deletion",
             "unaccepted wrapper `command`"),
            # 5. A git global option the exact strip missed.
            (f'git -C "{repo}" push origin issue-402-topic', "push",
             "git -C takes one unquoted directory word followed by a single space"),
            # 6. An unknown flag.
            ("git push --force origin issue-402-topic", "push", "unknown flag --force"),
            (f"{merge} --admin --delete-branch", "merge", "unknown flag --admin"),
            # 7. Structure, at the furthest point any form reached.
            ("gh pr merge 2342 --repo fagenorn/nix-config --delete-branch", "merge",
             "missing --merge"),
            ("gh pr merge --repo fagenorn/nix-config --merge --delete-branch", "merge",
             "missing <n>"),
            (f"{merge} --match-head-commit --delete-branch", "merge", "missing <sha>"),
            (release.replace("release create", "release new") + " /tmp/n.md",
             "release creation", "expected create, found new"),
            ('gh pr create --base main --repo fagenorn/nix-config --head issue-402-topic '
             '--title "x" --body "y"', "PR creation", "--base is out of place"),
            (f"{merge} --delete-branch --match-head-commit {sha}", "merge",
             "--match-head-commit is out of place"),
            ("git branch -d issue-402-topic extra", "branch deletion",
             "unexpected extra at the end"),
            # 8. Exact spelling.
            (f"{merge} --subject 'x' --delete-branch", "merge",
             "spell the merge exactly as the accepted form: single spaces, free text in "
             "double quotes"),
            # Slot values, with the value.
            ("git push origin HEAD:issue-402-topic", "push",
             "refspec HEAD:issue-402-topic is not accepted; name the branch alone"),
            ("git push origin +issue-402-topic", "push",
             "force-push refspec +issue-402-topic is not accepted"),
            ("git push origin heads/main", "push",
             "namespaced ref heads/main is not accepted; name the branch directly"),
            ("git push origin -topic", "push", "branch -topic must not begin with a dash"),
            ("git push origin refs/tags/v1.2", "push", "tag v1.2 is not a vMAJOR.MINOR.PATCH tag"),
            (f'{create} release --head issue-402-topic --title "x" --body "y"', "PR creation",
             "--base release is not one of main"),
            (f'{create} main --head issue-402-topic --title "$(id)" --body "y"', "PR creation",
             "title contains the forbidden character `$`"),
            ("gh pr merge 0 --repo fagenorn/nix-config --merge --delete-branch", "merge",
             "PR number 0 is not a positive decimal number"),
            ("gh pr merge 2342 --repo fagenorn/other --merge --delete-branch", "merge",
             "--repo fagenorn/other is not the current repository fagenorn/nix-config"),
            (f'{merge} --subject "bad $HOME" --delete-branch', "merge",
             "subject contains the forbidden character `$`"),
            (f"{merge} --match-head-commit {sha.upper()} --delete-branch", "merge",
             f"--match-head-commit {sha.upper()} is not 40 lowercase hexadecimal characters"),
            (f"{release} notes.md", "release creation",
             "--notes-file notes.md is not an absolute path without whitespace or "
             "shell-active characters"),
            ("git branch -d -topic", "branch deletion", "branch -topic must not begin with a dash"),
            # The release arm where no integration branch is declared.
            (merge, "merge", "missing --delete-branch: it may be omitted only in a repository "
                             "with a declared integration branch"),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=repo))
                self.assertIn(f"lifecycle guard: unsafe {label}: {problem}; accepted: ", line)
```

2. Existing rows whose problem became specific:
- `test_release_merge_arm_requires_exactly_integration_into_default`: assert `"may be omitted only when merging dev into main"` instead of `"--delete-branch may be omitted only when merging dev into main"`.
- `test_credential_scrub_prefix_forms_and_wrapper_near_misses`: delete `push_grammar` and `merge_grammar`, add `prefix = "unaccepted credential-scrub prefix"`, and give the refused rows these reasons, in order: `env -u PATH` → ``f"unsafe push: {prefix} `env -u PATH`"``; `env FOO=1` → `` `env FOO=1` ``; `env -i` → `` `env -i` ``; `env -u GITHUB_TOKEN -i` → `` `-i` ``; `env --unset=GITHUB_TOKEN` → `` `env --unset=GITHUB_TOKEN` ``; `sudo -u x` → ``"unsafe push: unaccepted wrapper `sudo -u x`"``; the repeated name → `` `-u GITHUB_TOKEN` ``; `env -uGITHUB_TOKEN` → `` `env -uGITHUB_TOKEN` ``; `env -u GITHUB_TOKEN --` → `` `--` ``; `env env -u GITHUB_TOKEN` → `` `env env -u GITHUB_TOKEN` ``; `env -u GITHUB_TOKEN env` → `` `env` ``; the push double space → `` `env -u GITHUB_TOKEN` (doubled space) ``; `{merge}; echo x` → ``"unsafe merge: forbidden character `;`: run the merge as its own Bash call"``; merge repeated name → ``f"unsafe merge: {prefix} `-u GITHUB_TOKEN`"``; `unset GITHUB_TOKEN GITHUB_TOKEN &&` → ``f"unsafe merge: {prefix} `unset GITHUB_TOKEN GITHUB_TOKEN &&`"``; both merge double spaces → ``f"unsafe merge: {prefix} `env -u GITHUB_TOKEN` (doubled space)"``; both branch-deletion rows → `"unsafe branch deletion: branch deletion takes no credential-scrub prefix"`; the `sudo … sh -c` row unchanged. Every push row above reads `f"unsafe push: {prefix} …"` unless named otherwise.
- `test_recognition_reads_through_global_options_and_paths`: the `gh -R fagenorn/nix-config pr create …` row's reason becomes `"unknown flag -R"`.
- `test_git_dash_c_is_judged_against_its_target_repository`: `grammar = "unsafe push: git -C takes one unquoted directory word followed by a single space"`.

3. In `tests/fixtures/guarded-command-shapes.json`: `branch.local` `prefixed` and `env_prefixed` reasons → `"branch deletion takes no credential-scrub prefix"`; `branch.remote`'s three reasons → `"unknown flag --delete"`; `refused_shapes` reasons `push.redirect-pipe` → ``"forbidden character `>`"``, `merge.after-cd` → ``"forbidden character `&`"``, `merge.then-echo` → ``"forbidden character `;`"``, `branch.after-cd` → ``"forbidden character `&`"``; `invocation_shapes` `merge.flag-before-path` and `merge.flag-between-path` → `"--repo is out of place"`. Leave every other member as it is.

- [ ] **Step 2: Run the tests and watch them fail**

Run the guard-suite invocation with `-k test_the_retro_commands_name_their_problem_and_cure -k test_refusals_name_the_first_problem -k test_credential_scrub_prefix_forms_and_wrapper_near_misses -k test_every_guarded_command_shape_gets_its_verdict -k test_every_invocation_shape_gets_its_verdict -k test_git_dash_c_is_judged_against_its_target_repository -k test_recognition_reads_through_global_options_and_paths -k test_release_merge_arm_requires_exactly_integration_into_default`.
Expected: FAIL — the guard still prints Task 1's generic problems (`expected exactly …`, `command does not match the guarded merge grammar`, `forbidden raw command character`).

- [ ] **Step 3: Write the minimal implementation**

**3a. `form_problem` and its helpers** (exact precedence and wire text; write it as given):

```python
# Characters that join or redirect a command: their refusal adds the run-alone advice (D5).
ADVISED_CHARACTERS = frozenset(";&|<>\n")


def shown_character(character):
    """`character` as a message shows it: itself, or its escape when it does not print."""
    return character if character.isprintable() else repr(character)[1:-1]


def forbidden_character(text, anywhere):
    """The first character of `text` in UNSAFE_BRANCH_CHARS, anywhere or only
    outside single and double quotes (a backslash escapes inside double quotes),
    else None."""
    quote = None
    index = 0
    while index < len(text):
        character = text[index]
        if quote == "'":
            if character == "'":
                quote = None
        elif quote == '"':
            if character == "\\":
                index += 1
            elif character == '"':
                quote = None
        elif not anywhere and character in "'\"":
            quote = character
        elif character in UNSAFE_BRANCH_CHARS:
            return character
        index += 1
    return None


def doubled_space_before(text, program):
    """Whether the raw text before the first whitespace-delimited `program` word
    holds two whitespace characters in a row."""
    match = re.search(rf"(?<!\S){re.escape(program)}(?!\S)", text)
    head = text[:match.start()] if match else text
    return re.search(r"\s\s", head) is not None


def element_spelling(element):
    """How a refusal names a form element: its word, or the slot as the form spells it."""
    if isinstance(element, Literal):
        return element.word
    if element.quoted:
        return f'"<{element.name}>"'
    return f"{element.prefix}<{element.name}>"


def structure_problem(compiled, words):
    """Step 7 (issue 402 D4, D16): read at the furthest point any form reached, ties
    to table order; None when every word matched a form."""
    best = None
    for form in compiled.forms:
        walk = walk_form(form.elements, words, compiled.flags)
        if walk.expected is None and walk.position == len(words):
            return None
        if best is None or walk.position > best.position:
            best = walk
    found = words[best.position] if best.position < len(words) else None
    if best.expected is None:
        if found in compiled.flags:
            return f"{found} is out of place"
        return f"unexpected {found} at the end"
    expected = element_spelling(best.expected)
    if found is None:
        return f"missing {expected}"
    if (isinstance(best.expected, Literal) and not best.expected.word.startswith("-")
            and not found.startswith("-")):
        return f"expected {expected}, found {found}"
    if isinstance(best.expected, Slot) or best.expected.word not in words[best.position:]:
        return f"missing {expected}"
    return f"{found} is out of place"


def form_problem(operation, compiled, text):
    """The first problem (issue 402 D4) of `text`, which `match_form` refused."""
    label = OPERATION_LABELS[operation]
    try:
        words, quoting = shlex.split(text), None
    except ValueError as error:
        words, quoting = None, f"invalid command quoting: {error}"
    start = None
    if words is not None and compiled.program in words:
        start = words.index(compiled.program)
    before = words[:start] if start else []
    if before and (before[0] in ("unset", "env") or before[0].startswith("-")):
        if not compiled.scrub_prefix:
            return f"{label} takes no credential-scrub prefix"
        problem = f"unaccepted credential-scrub prefix `{' '.join(before)}`"
        if doubled_space_before(text, compiled.program):
            problem += " (doubled space)"
        return problem
    character = forbidden_character(text, anywhere=compiled.whole_text_characters)
    if character is not None:
        problem = f"forbidden character `{shown_character(character)}`"
        if character in ADVISED_CHARACTERS:
            problem += (f": run the {label} as its own Bash call and read its output "
                        "with a follow-up call")
        return problem
    if quoting is not None:
        return quoting
    if before:
        return f"unaccepted wrapper `{' '.join(before)}`"
    if start is None:
        return "does not match an accepted form"
    rest = words[start:]
    if compiled.program == "git" and len(rest) > 1 and rest[1].startswith("-"):
        if rest[1] == "-C":
            return "git -C takes one unquoted directory word followed by a single space"
        return f"git global option {rest[1]} is not accepted"
    for index, word in enumerate(rest):
        if index and rest[index - 1] in compiled.quoted_value_flags:
            continue
        if word.startswith("-") and word not in compiled.flags:
            return f"unknown flag {word}"
    problem = structure_problem(compiled, rest)
    if problem is not None:
        return problem
    if compiled.exact_spelling:
        return (f"spell the {label} exactly as the accepted form: single spaces, "
                "free text in double quotes")
    return "does not match an accepted form"
```

**3b. Slot and arm texts.** Every one is a text refusal with Task 2's forms unless marked state; `<v>` is the value.

| Where | Problem text |
|---|---|
| `branch_name_problem` (in base order) | `branch name must not be empty`; `branch <v> must not begin with a dash`; `refspec <v> is not accepted; name the branch alone` (`:`); `force-push refspec <v> is not accepted` (`+`); ``branch <v> contains the forbidden character `<c>` ``; `namespaced ref <v> is not accepted; name the branch directly`; `BRANCH_VALIDATION_TIMEOUT` (state); `invalid branch name <v>` |
| `free_text_problem` | `must not be empty`; ``contains the forbidden character `<c>` `` (the first, via `shown_character`); `contains an unpaired surrogate` — callers prefix the slot name (`title …`, `body …`, `subject …`) |
| PR creation | head: `head <branch_name_problem>`; `--repo <v> is not the current repository <slug>` (as at base); `--base <v> is not one of <sorted authorized bases joined by ", ">` |
| push tag, release `<vX.Y.Z>` | `tag <v> is not a vMAJOR.MINOR.PATCH tag` |
| merge | `PR number <v> is not a positive decimal number`; `--repo <v> is not the current repository <slug>`; `subject <free_text_problem>`; the `<sha>` text unchanged |
| release creation | `--repo <v> is not the current repository <slug>`; `title <free_text_problem>`; `--notes-file <v> is not an absolute path without whitespace or shell-active characters` |
| branch deletion | `branch <v> must not begin with a dash`; `invalid branch name <v>`; the timeout stays state |
| merge arms | release form, no integration branch: `missing --delete-branch: it may be omitted only in a repository with a declared integration branch`; `validate_release_merge` mismatch with a head that is not permanent: `missing --delete-branch: it may be omitted only when merging <integration> into <default>; this PR merges <head> into <base>`; with a permanent head base's text without `missing` (state); the feature arm's `--delete-branch would delete the permanent branch <head>` unchanged |

Delete Task 1's per-operation legacy dictionary. Where the merge and release validators refused a slot with `form_problem`, refuse with that slot's text instead.

- [ ] **Step 4: Verify**

1. Run the full guard-suite invocation. Expected: `OK`, every test green.
2. No generic problem survives: `if grep -nE 'expected exactly|does not match the guarded|forbidden raw command character|refspecs and force-pushes' home/common/claude-code/lifecycle_guard.py; then exit 1; fi`
3. The shell-example run (the fixture changed). Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py tests/fixtures/guarded-command-shapes.json
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(guard): refusals name the first problem (issue 402)" \
  -m "<session trailers>"
```
