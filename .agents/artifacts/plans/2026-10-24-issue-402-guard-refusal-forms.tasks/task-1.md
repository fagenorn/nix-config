# Task 1: Form table, fail-closed compile and the shared matcher; the merge takes `--match-head-commit`

Spec § Merge grammar, § The form table, § Matching; per D1, D2, D10, D14, D16. After this task every accepted spelling lives in one literal `FORM_TABLE`; `main` compiles it first on every invocation; one matcher replaces `parse_merge_raw`, `parse_release_raw`, the merge and release argv cross-checks, the push and branch-deletion argv patterns and `PR_CREATE_FLAGS`; and both merge arms accept `[--match-head-commit <sha>]` after `--subject` and before `--delete-branch`. Messages stay as at base: Task 2 adds the accepted-forms clause and Task 3 names problems, so this task edits no existing line of the guard suite.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes (base): `UNSAFE_BRANCH_CHARS`, `SEMVER_TAG`, `OPERATION_LABELS`, `block(reason)`, `free_text_problem(value, allow_newlines)`, `branch_name_problem(git_bin, branch, timeout)`, `ownership_problem(context)`, `authorized_bases(repository, base_branch, integration_bases)`, `validate_tag_push(tag, context)`, `validate_release_merge(pr_facts, base, integration_base, context)`, `strip_scrub_prefix(text)`, `strip_spelling(text, spelling)`; in the suite `make_repo(origin)`, `run_guard(command, cwd=None, env=None)`, `RELEASE_PR`, `release_env(**overrides)`, `NODO`.
- Produces (later tasks use these exact names):
  - `FORM_SLOTS = ("n", "slug", "base", "branch", "sha", "subject", "title", "body", "vX.Y.Z", "path")`
  - `FORM_TABLE` (the literal in Step 3a) and `HEAD_COMMIT = re.compile(r"[0-9a-f]{40}")`
  - namedtuples `Literal(word)`, `Slot(name, quoted, prefix)`, `Group(elements)`, `CompiledForm(id, template, note, elements)`, `CompiledOperation(operation, forms, whole_text_characters, exact_spelling, scrub_prefix, program, flags, quoted_value_flags)`, `FormWalk(position, expected, values, quoted)`, `FormMatch(form, values)`
  - `class FormTableError(ValueError)`
  - `compile_form_table(table: dict) -> dict[str, CompiledOperation]`
  - `walk_form(elements: tuple, words: list[str], flags: frozenset[str]) -> FormWalk`
  - `match_form(compiled: CompiledOperation, text: str) -> FormMatch | None`
  - `form_problem(operation: str, compiled: CompiledOperation, text: str) -> str` (Task 3 rewrites its body, keeps its signature)
  - `validate_push(text, context, compiled)`, `validate_pr_create(text, context, compiled)`, `validate_merge(text, context, compiled)`, `validate_release(text, context, compiled)`, `validate_branch_delete(text, git_bin, timeout, compiled)`; `canonical_text(operation, text, directory)` keeps its signature.
  - In the suite: class attribute `HEAD_SHA = "d4d9acc0505c73305b3e0ced029db43100bc0e8a"`.

**Invariants:**
- Verdicts (D2): every command keeps base `ca3e4423`'s exit status except a merge carrying `--match-head-commit <sha>` in its place; every existing guard-suite row passes unedited.
- Matching (D16): an unquoted slot takes one word that is not a flag of its operation's forms; a quoted slot takes any one word; a glued slot takes a word beginning with its literal, its value the rest (possibly empty); an optional group is entered only when the next word is its flag; the first form in table order that consumes every word wins. The tag form precedes the branch form, so `git push -u origin refs/tags/v1.2.3` still reaches the branch arm.
- Exact spelling: for the merge and release creation the matched words, joined by single spaces with each quoted-slot word in double quotes, must equal the canonical text.
- Slot checks run in base order: merge `<n>` (non-empty, digits only, value > 0, leading zeros allowed as at base) → `<slug>` equals `context.repository` → `<subject>` passes `free_text_problem(value, False)` → `<sha>` `HEAD_COMMIT.fullmatch`; release `<vX.Y.Z>` `SEMVER_TAG.fullmatch` → `<slug>` → `<title>` free text without newlines → `<path>` absolute, no whitespace, no `UNSAFE_BRANCH_CHARS`; push and PR creation exactly their base checks; branch deletion exactly its two base checks (dash-led, `git check-ref-format`), never `branch_name_problem` (D16).
- `FORM_TABLE` is a plain literal; `compile_form_table` is the first call `main` makes, inside the `__main__` handler, so a template that does not compile refuses every call with exit 2 (D14).
- The guard reads `--match-head-commit`'s value only for its spelling; the PR lookup argv is unchanged (D10).

- [ ] **Step 0: Record the start**

Run: `git rev-parse HEAD` and keep the printed SHA; Step 4 calls it `<START>`.

- [ ] **Step 1: Write the failing test**

In `tests/test_claude_permission_guard.py`, add directly after `test_release_merge_arm_keeps_the_open_pr_predicate` (before `test_prefixed_merge_near_misses_fail_closed`):

```python
    # The PR head commit a merge may pin (issue 402 D10): the guard checks only its spelling.
    HEAD_SHA = "d4d9acc0505c73305b3e0ced029db43100bc0e8a"

    def test_merge_takes_an_optional_head_commit_flag(self):
        """Issue 402 AC1, D10: `--match-head-commit <40 lowercase hex>` stands after
        `--subject` and before `--delete-branch`, optional in both arms."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        sha = self.HEAD_SHA
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge"
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []})}
        for command, cwd, env in (
            (f"{merge} --match-head-commit {sha} --delete-branch", repo, None),
            (f'{merge} --subject "feature (#402)" --match-head-commit {sha} --delete-branch',
             repo, None),
            (f"unset GITHUB_TOKEN && {merge} --match-head-commit {sha} --delete-branch",
             repo, None),
            (f"env -u GITHUB_TOKEN {merge} --match-head-commit {sha} --delete-branch",
             repo, None),
            (f"gh pr merge 2342 --repo {NODO} --merge --match-head-commit {sha} --delete-branch",
             nodo, feature_into_dev),
            (f"gh pr merge 1484 --repo {NODO} --merge --match-head-commit {sha}",
             nodo, self.release_env()),
            (f'gh pr merge 1484 --repo {NODO} --merge --subject "merge: dev (dev → main)" '
             f"--match-head-commit {sha}", nodo, self.release_env()),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=cwd, env=env)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        for command in (
            f"{merge} --match-head-commit {sha[:39]} --delete-branch",           # 39 characters
            f"{merge} --match-head-commit {sha}0 --delete-branch",               # 41 characters
            f"{merge} --match-head-commit {sha.upper()} --delete-branch",        # uppercase
            f"{merge} --match-head-commit={sha} --delete-branch",                # attached value
            f'{merge} --match-head-commit {sha} --subject "x" --delete-branch',  # before --subject
            f"{merge} --delete-branch --match-head-commit {sha}",                # after --delete-branch
            f"{merge} --match-head-commit --delete-branch",                      # no value
            f"{merge} --match-head-commit {sha} {sha} --delete-branch",          # two values
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)
```

- [ ] **Step 2: Run the test and watch it fail**

Run the guard-suite invocation (Global Constraints) with `-k test_merge_takes_an_optional_head_commit_flag`.
Expected: FAIL — the seven allowed rows exit 2 with `unsafe merge: command does not match the guarded merge grammar`.

- [ ] **Step 3: Write the minimal implementation**

**3a. The table and its types.** Add after `RAW_GLUE_CHARS`; delete `PR_CREATE_FLAGS`. Add `from collections import namedtuple` to the imports.

```python
# Every accepted spelling, one table per operation (issue 402 D1). A form is
# (id, template, note): words separated by single spaces; `<name>` is a slot
# taking one word, `"<name>"` a free-text slot whose value may begin with `-`;
# a slot may close a literal word (`refs/tags/<vX.Y.Z>`); `[...]` is an
# optional group whose first word is its flag, never nested; the note is
# printed after the form and never matched. Forms are tried in order. `main`
# compiles this literal first on every invocation (D14).
FORM_SLOTS = ("n", "slug", "base", "branch", "sha", "subject", "title", "body", "vX.Y.Z", "path")
FORM_TABLE = {
    "push": {
        "forms": (
            ("tag", "git push origin refs/tags/<vX.Y.Z>", None),
            ("branch", "git push [-u] origin <branch>", None),
        ),
        "whole_text_characters": True,
        "exact_spelling": False,
        "scrub_prefix": True,
    },
    "pr-create": {
        "forms": (
            ("pr-create", 'gh pr create --repo <slug> --base <base> --head <branch> '
                          '--title "<title>" --body "<body>"', None),
        ),
        "whole_text_characters": False,
        "exact_spelling": False,
        "scrub_prefix": True,
    },
    "merge": {
        "forms": (
            ("feature", 'gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] '
                        "[--match-head-commit <sha>] --delete-branch", None),
            ("release", 'gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] '
                        "[--match-head-commit <sha>]", "only <integration> into <default>"),
        ),
        "whole_text_characters": False,
        "exact_spelling": True,
        "scrub_prefix": True,
    },
    "release": {
        "forms": (
            ("release", 'gh release create <vX.Y.Z> --repo <slug> --verify-tag '
                        '--title "<title>" --notes-file <path>', None),
        ),
        "whole_text_characters": False,
        "exact_spelling": True,
        "scrub_prefix": True,
    },
    "branch": {
        "forms": (("branch", "git branch -d <branch>", None),),
        "whole_text_characters": True,
        "exact_spelling": False,
        "scrub_prefix": False,
    },
}
# The value `--match-head-commit` takes: a full commit SHA (issue 402 D10).
HEAD_COMMIT = re.compile(r"[0-9a-f]{40}")

Literal = namedtuple("Literal", "word")
Slot = namedtuple("Slot", "name quoted prefix")
Group = namedtuple("Group", "elements")
CompiledForm = namedtuple("CompiledForm", "id template note elements")
CompiledOperation = namedtuple(
    "CompiledOperation",
    "operation forms whole_text_characters exact_spelling scrub_prefix program flags "
    "quoted_value_flags",
)
FormWalk = namedtuple("FormWalk", "position expected values quoted")
FormMatch = namedtuple("FormMatch", "form values")


class FormTableError(ValueError):
    """A form-table entry that does not compile; `main` lets it reach the
    unexpected-failure handler, which refuses with exit 2 (issue 402 D14)."""
```

**3b. `compile_form_table(table) -> dict[str, CompiledOperation]`.** Raise `FormTableError` naming the operation and template when any of these holds; otherwise build one `CompiledOperation` per key:
- the table's keys are not exactly `{"push", "pr-create", "merge", "release", "branch"}`; an entry's keys are not exactly `{"forms", "whole_text_characters", "exact_spelling", "scrub_prefix"}`; a property is not a `bool`;
- `forms` is not a non-empty tuple of `(id, template, note)` with `str` id and template and `str`-or-`None` note, or two forms share an id;
- `template.split(" ")` yields an empty word;
- a `[` stands anywhere but at a word's start, or opens while a group is open; a `]` stands anywhere but at a word's end, or closes no open group; a group is still open at the template's end, is empty, or does not begin with a literal starting with `-`;
- a bracket-stripped word is neither a literal (no `<`, `>`, `"`) nor a slot word: `<name>`, `"<name>"` or `<prefix><name>` with a non-empty prefix free of `<`, `>` and `"`; the name is not in `FORM_SLOTS`; a quoted slot has a prefix;
- a form's first element is not a literal, or the forms of one operation begin with different literals;
- a note names a `<…>` placeholder other than `<integration>` and `<default>`.

Computed per operation: `program` = the shared first literal (`"git"` or `"gh"`); `flags` = frozenset of every literal word beginning with `-` in any form, groups included; `quoted_value_flags` = frozenset of each such flag immediately followed in its form (or group) by a quoted slot (`--subject`, `--title`, `--body`). `CompiledForm.elements` is a tuple of `Literal`, `Slot` and `Group` (whose `elements` is a tuple of `Literal`/`Slot`).

**3c. The matcher** (verdict-critical; write it as given):

```python
def walk_form(elements, words, flags):
    """How far `words` follow a compiled form's `elements` from the first word.

    An optional group is entered only when the next word equals its flag; once
    entered, every element in it must match. A literal matches its own word; an
    unquoted slot takes one word not in `flags`; a glued slot takes a word that
    starts with its literal, its value the rest; a quoted slot takes any one
    word. `expected` is the element that could not be matched at `position`,
    None when every element matched; `quoted` holds the indices of the words
    quoted slots took.
    """
    position = 0
    values = {}
    quoted = set()

    def take(element):
        nonlocal position
        if position >= len(words):
            return False
        word = words[position]
        if isinstance(element, Literal):
            if word != element.word:
                return False
        elif element.quoted:
            values[element.name] = word
            quoted.add(position)
        elif element.prefix:
            if not word.startswith(element.prefix):
                return False
            values[element.name] = word[len(element.prefix):]
        elif word in flags:
            return False
        else:
            values[element.name] = word
        position += 1
        return True

    for element in elements:
        if isinstance(element, Group):
            if position < len(words) and words[position] == element.elements[0].word:
                for inner in element.elements:
                    if not take(inner):
                        return FormWalk(position, inner, values, frozenset(quoted))
            continue
        if not take(element):
            return FormWalk(position, element, values, frozenset(quoted))
    return FormWalk(position, None, values, frozenset(quoted))


def match_form(compiled, text):
    """The first of `compiled`'s forms that `text` spells, with its slot values, else None
    (issue 402 D2): the whole-text character rule, the `shlex` words, the forms in
    table order, and for an exact-spelling operation the rendered form against `text`."""
    if compiled.whole_text_characters and any(c in UNSAFE_BRANCH_CHARS for c in text):
        return None
    try:
        words = shlex.split(text)
    except ValueError:
        return None
    for form in compiled.forms:
        walk = walk_form(form.elements, words, compiled.flags)
        if walk.expected is not None or walk.position != len(words):
            continue
        if compiled.exact_spelling:
            rendered = " ".join(
                f'"{word}"' if index in walk.quoted else word
                for index, word in enumerate(words)
            )
            if rendered != text:
                return None
        return FormMatch(form, walk.values)
    return None
```

**3d. `form_problem` (base texts until Task 3):**

```python
def form_problem(operation, compiled, text):
    """Why `match_form` refused `text`."""
    if compiled.whole_text_characters and any(c in UNSAFE_BRANCH_CHARS for c in text):
        return "forbidden raw command character"
    try:
        shlex.split(text)
    except ValueError as error:
        return f"invalid command quoting: {error}"
    return {
        "push": "expected exactly git push [-u] origin <branch>",
        "pr-create": ("expected exactly gh pr create --repo <repo> --base <base> "
                      "--head <head> --title <title> --body <body>"),
        "merge": "command does not match the guarded merge grammar",
        "release": "command does not match the guarded release grammar",
        "branch": "expected exactly git branch -d <branch>",
    }[operation]
```

**3e. Validators.** Each takes the operation's `CompiledOperation` as `compiled`; every refusal text not named here is base's, verbatim, in base order.
- `validate_push(text, context, compiled)`: ownership → `match_form`; None → `block(f"unsafe push: {form_problem('push', compiled, text)}")`. Form `"tag"` → `return validate_tag_push(values["vX.Y.Z"], context)`; `"branch"` → `branch = values["branch"]` and base's branch-name, default-branch and default-push checks; any other id raises `AssertionError`.
- `validate_pr_create(text, context, compiled)`: ownership → `match_form` (None → `form_problem`) → `values["slug"]`, `["base"]`, `["branch"]` (the head), `["title"]`, `["body"]` through base's checks in base order.
- `validate_merge(text, context, compiled)`: ownership → `match_form` (None → `form_problem`) → a failed `<n>`, `<slug>` or `<subject>` check refuses with `block(f"unsafe merge: {form_problem('merge', compiled, text)}")` (base's grammar text) → a present `values["sha"]` that `HEAD_COMMIT.fullmatch` rejects refuses `unsafe merge: --match-head-commit <value> is not 40 lowercase hexadecimal characters` → `delete_branch` is True for form `"feature"`, False for `"release"`, `AssertionError` otherwise → base's code from the default-branch check on, unchanged, with `number = values["n"]`.
- `validate_release(text, context, compiled)`: ownership → `match_form` (None → `form_problem`) → a failed `<vX.Y.Z>`, `<slug>`, `<title>` or `<path>` check refuses with `form_problem('release', compiled, text)` → `return 0`.
- `validate_branch_delete(text, git_bin, timeout, compiled)`: `match_form` (None → `block(f"unsafe branch deletion: {form_problem('branch', compiled, text)}")`) → `values["branch"]` through base's dash-led and `git check-ref-format` checks only.
- Delete `parse_merge_raw` and `parse_release_raw`.

**3f. `canonical_text` and `main`.** In `canonical_text` replace `if operation != "branch":` with `if FORM_TABLE[operation]["scrub_prefix"]:` and say so in its docstring (the property, not a named verb, decides; branch deletion's entry has it False, issue 400 D2). Make `table = compile_form_table(FORM_TABLE)` the first statement of `main`, and pass `table[operation]` to each validator call.

**3g. README** (`home/common/claude-code/README.md`). In the `## Adjudicated verbs` paragraph that begins "The verbs it does adjudicate", replace the merge clause from "and `gh pr merge` as the generalized" through "instead of forge protection)" with: `gh pr merge <n> --repo <detected slug> --merge [--subject "<subject>"] [--match-head-commit <sha>] --delete-branch`, flags in that order, `<sha>` one separate word of exactly 40 lowercase hex characters whose spelling alone the guard checks (gh hands it to GitHub, which refuses the merge atomically if the PR head differs; issue 402), or, in a repository with a declared integration branch, the release arm: the same form without `--delete-branch`, only the integration branch merged into the default branch, gated on a fully green check rollup instead of forge protection. Then add one sentence at the end of that paragraph: every accepted spelling has one home, `FORM_TABLE` in `lifecycle_guard.py` (issue 402), each operation's forms in its template notation (`<slot>` one word, `"<slot>"` one free-text word that may begin with `-`, a slot closing a literal word, `[…]` an optional group led by its flag, a parenthesised note never matched) with three properties — whole-text characters (push and branch deletion), exact spelling (merge and release creation: single spaces, double-quoted free text) and scrub prefix (every operation but branch deletion) — compiled first on every invocation inside the unexpected-failure handler, so a template that does not compile refuses every Bash call with exit 2 and fails `just build`; one shared matcher judges each canonical command against its operation's forms in table order, and `canonical_text` reads the scrub-prefix property.

- [ ] **Step 4: Verify**

1. Run the full guard-suite invocation. Expected: `OK`, every test green, the new one included.
2. Existing rows untouched: `if git diff <START> -- tests/test_claude_permission_guard.py | grep -q '^-[^-]'; then echo "an existing guard-suite line changed"; exit 1; fi`
3. The old parsers are gone: `if grep -nE 'def parse_merge_raw|def parse_release_raw|PR_CREATE_FLAGS' home/common/claude-code/lifecycle_guard.py; then exit 1; fi`
4. README: `grep -qF -- '[--match-head-commit <sha>]' home/common/claude-code/README.md && grep -qF 'FORM_TABLE' home/common/claude-code/README.md || exit 1`
5. D14 by hand (D17), with `./result` from item 1:

```bash
set -e
SCRATCH=$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)/d14
mkdir -p "$SCRATCH" && cp home/common/claude-code/lifecycle_guard.py "$SCRATCH/guard.py"
BASE_POLICY=$(nix-store --query --requisites ./result | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$')
probe() { printf '%s' '{"tool_name":"Bash","tool_input":{"command":"true"}}' \
  | python3 -I "$SCRATCH/guard.py" --base-policy "$BASE_POLICY" --policy "$SCRATCH/none.json" --derive-bin /usr/bin/false; }
probe; echo "intact: $?"
python3 - "$SCRATCH/guard.py" <<'EOF'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
old = '"git branch -d <branch>"'
assert text.count(old) == 1, text.count(old)
open(path, "w", encoding="utf-8").write(text.replace(old, '"git branch -d <nope>"'))
EOF
set +e; probe; echo "broken: $?"
```

Expected: `intact: 0`; then `lifecycle guard: unexpected failure: FormTableError: …` and `broken: 2`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(guard): one form table and matcher; merge takes --match-head-commit (issue 402)" \
  -m "<session trailers>"
```
