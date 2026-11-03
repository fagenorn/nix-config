# Task 1: Spec-format and code map assert helpers

Background for a reader with no context. Skill evals are graded by shell snippets that run with `home/common/agent-skills/evals/assert-lib.sh` sourced. Issue 354 makes the `design` skill leave a **code map**: a short Markdown file listing, for each thing a design spec decides about, where it lives in the code. This task adds the two helpers that later eval cases call: one checks that a spec's `## Decisions` section names no file path or line number, the other checks a code map's form. A code map looks like this:

```markdown
# Code map: 2026-10-11-list-state-design.md

## The list command
- Why: it gains the state filter
- Code: `tinytask/cli.py` (`build_parser()`, `main`); `tinytask/model.py` (`STATES`)
- Tests: `tests/test_cli.py` (`CliTest`)
```

A path is repository-relative and stands outside parentheses; the symbols or test names that belong to it follow in parentheses. `Tests:` may read `none read`.

**Files:**
- Modify: `home/common/agent-skills/evals/assert-lib.sh` (append two functions at the end)
- Test: `home/common/agent-skills/tests/test_eval_cases.py` (one module-level function and two classes, inserted before the final `if __name__ == "__main__":` block)

**Interfaces:**
- Consumes: from `test_eval_cases.py`, `run_assert(shell, cwd, *, stdin=subprocess.DEVNULL, **env)`, `EVALS_DIR`, and the fixture at `EVALS_DIR / "fixture-repo"`, which tracks `tinytask/cli.py`, `tinytask/model.py`, `tinytask/store.py` and `tests/test_cli.py`. From `assert-lib.sh`, `fail`.
- Produces, for Task 3:
  - `spec_decisions_path_free <spec> <repo>`: exit 0 when the spec's `## Decisions` section is clean, non-zero otherwise, one line per offender on stdout.
  - `code_map_valid <map> <repo> [required-path...]`: exit 0 when the code map is valid, non-zero otherwise, one line per defect on stdout.
  - `fixture_sandbox(tmp) -> (repo: Path, git: list[str])` in `test_eval_cases.py`: the tinytask fixture copied to `tmp/repo`, committed once on `main`, with `refs/remotes/origin/main` at that commit; `git` is the argv prefix that commits unsigned as the eval identity.

**Invariants:**
- `spec_decisions_path_free` reads only the lines between a line equal to `## Decisions` (case-insensitive) and the next line starting `## `. A spec without that heading fails with `heading not found: ## Decisions`.
- An offender is: the repository-relative path of a file `git -C <repo> ls-files` lists, found as a substring; a file name whose extension starts with a letter, followed by `:<number>`; `#L<number>`; or the word `line` or `lines`, in any case, followed by whitespace and a number (D5, D11). Offender lines start `tracked path in Decisions: ` or `line reference in Decisions: `.
- `code_map_valid` fails with `not a file: <map>` on a missing file and with a line containing ``no `## ` entry`` on a file without a `## ` heading.
- Every entry needs a `Why:` line and a `Code:` line that names at least one path; the defect line names the entry's heading.
- A path is a backticked token outside balanced parentheses on a `Code:` or `Tests:` line, so a symbol written with call parentheses inside the group is never read as a path (D11). Each such path must be a tracked file of `<repo>`; each required path must be among them.
- Neither helper exits the shell: each returns its status, like the helpers above them in the file.

- [ ] **Step 1: Write the failing tests**

Insert this block into `home/common/agent-skills/tests/test_eval_cases.py`, immediately before the final `if __name__ == "__main__":` line, with two blank lines before and after it. Extract it, do not retype it (`T` is this task file's path):

```bash
block task-1-tests "$T" > "$SCRATCH/task-1-tests.py"
python3 - "$SCRATCH/task-1-tests.py" <<'PY'
import pathlib, sys
path = pathlib.Path("home/common/agent-skills/tests/test_eval_cases.py")
text = path.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n'
assert text.count(marker) == 1
block = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
path.write_text(text.replace(marker, "\n\n" + block.rstrip("\n") + "\n" + marker), encoding="utf-8")
PY
```

```python
# begin task-1-tests
def fixture_sandbox(tmp):
    """The tinytask fixture as a committed repo whose origin/main is its only commit."""
    repo = Path(tmp) / "repo"
    shutil.copytree(EVALS_DIR / "fixture-repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
    git = ["git", "-C", str(repo), "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
           "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)
    subprocess.run(git + ["update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
    return repo, git


class SpecFormatCheckTest(unittest.TestCase):
    """#354: spec_decisions_path_free reads only the Decisions section (D5)."""

    def check(self, spec_text):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = fixture_sandbox(Path(tmp).resolve())
            spec = Path(tmp).resolve() / "spec.md"
            spec.write_text(spec_text, encoding="utf-8")
            return run_assert('spec_decisions_path_free "$SPEC" "$REPO"', repo,
                              SPEC=str(spec), REPO=str(repo))

    def test_a_tracked_path_in_decisions_fails_and_is_named(self):
        done = self.check("# S\n\n## Decisions\n\nThe filter lands in tinytask/cli.py.\n\n## Test seams\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("tinytask/cli.py", done.stdout)

    def test_the_same_path_under_test_seams_only_passes(self):
        done = self.check("# S\n\n## Decisions\n\n### Command line\n\nThe list command gains a filter.\n\n"
                          "## Test seams\n\nPrior art: tinytask/cli.py, tests/test_cli.py:12.\n")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_each_line_reference_form_fails(self):
        for reference in ("see parser.py:12", "the anchor #L33", "at line 40", "Lines 3 to 5"):
            with self.subTest(reference=reference):
                done = self.check(f"# S\n\n## Decisions\n\nThe filter, {reference}.\n")
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("line reference", done.stdout)

    def test_a_spec_without_a_decisions_section_fails(self):
        done = self.check("# S\n\n## Problem\n\nNo way to list done tasks.\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("## Decisions", done.stdout)


class CodeMapCheckTest(unittest.TestCase):
    """#354: code_map_valid grades a code map's form, its paths and its coverage (D6)."""

    REQUIRED = ("tinytask/cli.py", "tinytask/model.py", "tests/test_cli.py")
    GOOD = ("# Code map: 2026-10-11-list-state-design.md\n\n"
            "## The list command\n"
            "- Why: it gains the state filter\n"
            "- Code: `tinytask/cli.py` (`build_parser()`, `main`); `tinytask/model.py` (`STATES`)\n"
            "- Tests: `tests/test_cli.py` (`CliTest`)\n\n"
            "## The task store\n"
            "- Why: the filter reads tasks through it\n"
            "- Code: `tinytask/store.py`\n"
            "- Tests: none read\n")

    def check(self, map_text, *required):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = fixture_sandbox(Path(tmp).resolve())
            code_map = Path(tmp).resolve() / "spec.code-map.md"
            if map_text is not None:
                code_map.write_text(map_text, encoding="utf-8")
            return run_assert('code_map_valid "$MAP" "$REPO" $REQUIRED', repo,
                              MAP=str(code_map), REPO=str(repo), REQUIRED=" ".join(required))

    def test_a_valid_map_passes(self):
        done = self.check(self.GOOD, *self.REQUIRED)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_missing_file_fails(self):
        done = self.check(None)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("not a file", done.stdout)

    def test_a_map_with_no_entry_fails(self):
        done = self.check("# Code map: 2026-10-11-list-state-design.md\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("no `## ` entry", done.stdout)

    def test_an_entry_without_a_code_line_fails_and_is_named(self):
        done = self.check(self.GOOD + "\n## The help text\n- Why: it lists the option\n- Tests: none read\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("## The help text", done.stdout)

    def test_an_untracked_listed_path_fails_and_is_named(self):
        done = self.check(self.GOOD.replace("`tinytask/store.py`", "`tinytask/filters.py`"))
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("tinytask/filters.py", done.stdout)

    def test_an_absent_required_path_fails_and_is_named(self):
        done = self.check(self.GOOD, *self.REQUIRED, "tests/test_store.py")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("tests/test_store.py", done.stdout)

    def test_a_symbol_in_parentheses_is_not_read_as_a_path(self):
        done = self.check(self.GOOD.replace("(`STATES`)", "(`STATES`, `not/a/tracked/file.py`)"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
# end task-1-tests
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py -k SpecFormatCheckTest -k CodeMapCheckTest 2>&1 | tail -n 3`
Expected: FAIL — `Ran 11 tests` and `FAILED (failures=14)` (the four line-reference forms fail as separate subtests); no test passes, because neither helper exists yet.

- [ ] **Step 3: Add the two helpers**

Append this block to the end of `home/common/agent-skills/evals/assert-lib.sh`, after one blank line. The full code is given because the parsing rules are the decision (D5, D11): the section bounds, the three line-reference forms, and the character scan that keeps a parenthesised group, call parentheses included, out of the path list.

```bash
printf '\n' >> home/common/agent-skills/evals/assert-lib.sh
block task-1-helpers "$T" >> home/common/agent-skills/evals/assert-lib.sh
```

```bash
# begin task-1-helpers
# spec_decisions_path_free <spec> <repo> — the spec's `## Decisions` section names no
# tracked file of <repo> by its repository-relative path and holds no line reference: a
# file name followed by `:<number>`, a `#L<number>` anchor, or the word `line` or `lines`
# followed by a number. Each offender is printed. A spec without the section fails; the
# other sections are not read. The heading matches case-insensitively.
spec_decisions_path_free() {
  local spec="$1" repo="$2" section tracked hits hit bad=0
  [ -f "$spec" ] || fail "not a file: $spec" || return 1
  tracked=$(git -C "$repo" ls-files) || fail "cannot list tracked files of: $repo" || return 1
  section=$(awk '
    tolower($0) == "## decisions" { inside = 1; found = 1; next }
    inside && /^## / { inside = 0 }
    inside { print }
    END { if (!found) exit 3 }
  ' "$spec") || fail "heading not found: ## Decisions" || return 1
  if [ -n "$tracked" ]; then
    hits=$(grep -oF -e "$tracked" <<<"$section" | sort -u)
    if [ -n "$hits" ]; then
      while IFS= read -r hit; do printf 'tracked path in Decisions: %s\n' "$hit"; done <<<"$hits"
      bad=1
    fi
  fi
  hits=$(grep -oiE -e '[[:alnum:]_./-]+\.[[:alpha:]][[:alnum:]]*:[0-9]+' -e '#L[0-9]+' \
    -e '(^|[^[:alpha:]])lines?[[:space:]]+[0-9]+' <<<"$section" | sort -u)
  if [ -n "$hits" ]; then
    while IFS= read -r hit; do printf 'line reference in Decisions: %s\n' "$hit"; done <<<"$hits"
    bad=1
  fi
  return "$bad"
}

# code_map_valid <map> <repo> [required-path...] — the code map is a file with at least
# one `## ` entry; every entry has a `Why:` line and a `Code:` line naming at least one
# path; every path on a `Code:` or `Tests:` line is a tracked file of <repo>; and every
# required path is listed. A path is a backticked token outside parentheses, so the
# symbols and test names in parentheses, call parentheses included, are never read as
# paths, and `Tests: none read` lists nothing.
code_map_valid() {
  local map="$1" repo="$2" tracked parsed listed path bad=0
  shift 2
  [ -f "$map" ] || fail "not a file: $map" || return 1
  tracked=$(git -C "$repo" ls-files) || fail "cannot list tracked files of: $repo" || return 1
  parsed=$(awk '
    function emit(line,    i, c, depth, open, token, count) {
      for (i = 1; i <= length(line); i++) {
        c = substr(line, i, 1)
        if (!open && c == "(") { depth++; continue }
        if (!open && c == ")") { if (depth > 0) depth--; continue }
        if (depth > 0) continue
        if (c != "`") { if (open) token = token c; continue }
        if (open) { if (token != "") { print "@path " token; count++ } token = "" }
        open = !open
      }
      return count
    }
    function close_entry() {
      if (!entries) return
      if (!why) print "@bad entry without a Why: line: " title
      if (!code) print "@bad entry without a Code: line naming a path: " title
    }
    /^## / { close_entry(); entries++; title = $0; why = 0; code = 0; next }
    !entries { next }
    /^[-*]?[[:space:]]*Why:/ { why = 1 }
    /^[-*]?[[:space:]]*Code:/ { if (emit($0) > 0) code = 1 }
    /^[-*]?[[:space:]]*Tests:/ { emit($0) }
    END { close_entry(); if (!entries) print "@bad the code map has no `## ` entry" }
  ' "$map")
  if grep -q '^@bad ' <<<"$parsed"; then
    grep '^@bad ' <<<"$parsed" | sed 's/^@bad //'; bad=1
  fi
  listed=$(grep '^@path ' <<<"$parsed" | sed 's/^@path //' | sort -u)
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    grep -qxF -- "$path" <<<"$tracked" || { echo "listed path is not a tracked file: $path"; bad=1; }
  done <<<"$listed"
  for path in "$@"; do
    grep -qxF -- "$path" <<<"$listed" || { echo "required path is not listed: $path"; bad=1; }
  done
  return "$bad"
}
# end task-1-helpers
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -n 3`
Expected: PASS — `Ran 30 tests` and `OK`. A count below 30 means the test block was not inserted; any failure means the task is incomplete.

Run: `bash -n home/common/agent-skills/evals/assert-lib.sh && echo syntax-ok`
Expected: `syntax-ok`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/evals/assert-lib.sh home/common/agent-skills/tests/test_eval_cases.py
git commit -m "test(evals): add the spec-format and code map assert helpers (#354)"
```
