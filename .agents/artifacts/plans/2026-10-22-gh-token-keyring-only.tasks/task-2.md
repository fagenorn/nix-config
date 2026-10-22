# Task 2: Restate the scrub rationale at the four wrong-cause sites

Spec § Decisions (Corrected rationale, three sites), per D4 and D6, with verification per D7. Four living texts still blame a shell or harness token for the guard's token scrub. This task rewrites each to the new rationale: the keyring credential is the authority, and an ambient token, when one is present, may be narrower. It changes comments and prose only, runs the guard suite against the build, and fills `AC4` and `AC5` of the acceptance record.

**Files:**
- Modify: `CLAUDE.md` (line 53, one clause)
- Modify: `home/common/claude-code/lifecycle_guard.py` (the comment above `GH_ENV_TOKEN_NAMES`, lines 47–52)
- Modify: `home/common/claude-code/README.md` (line 17, one clause)
- Modify: `tests/test_claude_permission_guard.py` (the comment inside `FAKE_GH_SCRIPT`, lines 42–44; D6)
- Modify: `.agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md` (rows `AC4`, `AC5`)

**Interfaces:**
- Consumes (Task 1): the acceptance record with rows `AC1`–`AC7`; a module that exports no GitHub token, which the new `CLAUDE.md` sentence describes.
- Produces: no code interface. `GH_ENV_TOKEN_NAMES`, `UNSET_GITHUB_TOKEN_PREFIX`, `gh_lookup_env` and the fake `gh`'s scrub loop are byte-identical to `336d9e05`.

**Invariants:**
- In `lifecycle_guard.py` and `tests/test_claude_permission_guard.py`, every added or removed line is a `#` comment line (D4, D6).
- No edited text contains `shell exports`, `harness exports`, or `exports` followed by one character and `GITHUB_TOKEN` (D4).
- No new comment line puts `UNSET_GITHUB_TOKEN_PREFIX = "` at the start of a line. `test_shell_example_contracts.py` reads the guard's single such assignment.
- `python/README.md`, `python/agent_tools/forge_adapter.py`, the `harness-token` fixture values and `tests/forge_world.py`'s docstring stay unchanged (D4, D6).

- [ ] **Step 1: Write the gate script**

Save as `<scratch>/i399/task2-check.sh` (the `launch-scope scratch` root):

```bash
#!/usr/bin/env bash
# Task 2 gate (issue 399): the four rationale sites. Usage, from the worktree root: bash task2-check.sh
set -euo pipefail
fail=0
# grep_none LABEL <git grep args>: git grep exit 1 is zero matches, exit 0 lists
# matches and fails the gate, any other exit is a git error and aborts (exit 2).
grep_none() {
  local label=$1; shift; local rc=0
  git grep -n "$@" || rc=$?
  case $rc in
    0) echo "$label: the lines above still match"; fail=1 ;;
    1) echo "$label: zero matches (git grep exit 1)" ;;
    *) echo "$label: git grep failed (exit $rc)"; exit 2 ;;
  esac
}

# AC5: no living doc or comment claims the shell or harness exports a GitHub token.
grep_none "AC5" -e 'shell exports' -e 'harness exports' -e 'exports .GITHUB_TOKEN' -- CLAUDE.md home python

# D6: the old wording is gone from the guard, its README and its suite.
grep_none "D6" -e 'harness token is narrower' -e 'fine-grained PAT' -e 'fine-grained GITHUB_TOKEN' \
  -- home/common/claude-code tests/test_claude_permission_guard.py

# The new rationale is present at each site.
grep -qF 'exports `HF_TOKEN` into the shell. The sops store holds no GitHub token and the shell receives none' CLAUDE.md \
  || { echo "CLAUDE.md: new sentence missing"; fail=1; }
grep -qxF '# The gh keyring credential is the authority for these lookups. gh prefers an' \
  home/common/claude-code/lifecycle_guard.py || { echo "lifecycle_guard.py: new comment missing"; fail=1; }
grep -qF 'rather than any ambient environment token, which gh would prefer and which may be narrower; a machine with no keyring auth' \
  home/common/claude-code/README.md || { echo "README.md: new clause missing"; fail=1; }
grep -qxF '# ambient token, which gh would prefer, may be narrower than the keyring' \
  tests/test_claude_permission_guard.py || { echo "guard suite: new comment missing"; fail=1; }

# D4, D6: the guard and its suite change in comment lines only.
# The diff runs on its own first, so a git error aborts the gate under set -e.
diff=$(git diff -U0 336d9e05 -- home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py)
if printf '%s\n' "$diff" | grep -E '^[-+]' | grep -vE '^(\+\+\+|---) ' | grep -vE '^[-+]#'; then
  echo "the lines above are non-comment changes"; fail=1
fi

echo "task2-check exit $fail"
exit "$fail"
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `bash <scratch>/i399/task2-check.sh`. Expected: exit 1. The `AC5` block lists `CLAUDE.md:53`, `home/common/claude-code/README.md:17` and `home/common/claude-code/lifecycle_guard.py:47`. The `D6` block lists the README and guard lines again, plus `tests/test_claude_permission_guard.py:43`. All four `… missing` lines print, and the last line is `task2-check exit 1`.

- [ ] **Step 3: Rewrite the four sites**

Each replacement is exact. The old text occurs once in its file.

`CLAUDE.md`, inside the **Secrets via sops-nix + age.** paragraph. Old:

```
declares which secrets get decrypted and exports `GITHUB_TOKEN`/`HF_TOKEN` into the shell.
```

New (the paragraph's next sentence, `To add a secret: …`, follows unchanged):

```
declares which secrets get decrypted and exports `HF_TOKEN` into the shell. The sops store holds no GitHub token and the shell receives none: `gh` authenticates only through its `gh auth login` credential (the macOS keychain, gh's own store on `anis-desktop`), and a host without one needs a one-time `gh auth login`.
```

`home/common/claude-code/lifecycle_guard.py`, the six comment lines directly above `GH_ENV_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")`. Old:

```python
# The harness exports a fine-grained GITHUB_TOKEN that gh prefers over the
# keyring credential, and its reach is narrower — it cannot see every
# authorized owner's org. The guard's forge lookups drop the env tokens so
# validation observes GitHub with the keyring credential, the same auth
# the `unset GITHUB_TOKEN && ` form of the guarded command will use. A
# machine with no keyring auth still fails closed at the lookup.
```

New:

```python
# The gh keyring credential is the authority for these lookups. gh prefers an
# ambient GITHUB_TOKEN/GH_TOKEN over it, and such a token, when one is present
# (CI, a one-off export, another tool), may be narrower: it may not see every
# authorized owner's org. The guard's forge lookups drop the env tokens, so
# validation observes GitHub with the keyring credential: the auth the guarded
# command uses when it sees neither env token (none is set, or the
# `unset GITHUB_TOKEN && ` prefix removed the only one). A machine with no
# keyring auth still fails closed at the lookup.
```

The new comment says "removed the only one" because the prefix unsets `GITHUB_TOKEN` alone, not `GH_TOKEN`. That matches `UNSET_GITHUB_TOKEN_PREFIX` and `gh_lookup_env` as they stand.

`home/common/claude-code/README.md`, line 17, the sentence that begins "The merge's own `gh` lookups run with". Old:

```
rather than the narrower fine-grained PAT the shell exports;
```

New (the rest of the sentence, including `(whose reach covers every authorized owner)` before it and `a machine with no keyring auth fails closed at the lookup.` after it, stays):

```
rather than any ambient environment token, which gh would prefer and which may be narrower;
```

`tests/test_claude_permission_guard.py`, the comment inside the `FAKE_GH_SCRIPT` string, directly above `for name in ("GITHUB_TOKEN", "GH_TOKEN"):` (D6). Old:

```python
# The guard must scrub the gh-recognised token variables from its lookups (the
# harness token is narrower than the keyring credential). Refusing to answer
# when one is visible makes every merge-path test double as that assertion.
```

New:

```python
# The guard must scrub the gh-recognised token variables from its lookups (an
# ambient token, which gh would prefer, may be narrower than the keyring
# credential). Refusing to answer when one is visible makes every merge-path
# test double as that assertion.
```

- [ ] **Step 4: Run the gate and watch it pass**

Run: `bash <scratch>/i399/task2-check.sh`. Expected: exactly the three lines `AC5: zero matches (git grep exit 1)`, `D6: zero matches (git grep exit 1)` and `task2-check exit 0`, and exit 0.

Check: `git diff --numstat -- CLAUDE.md home tests` prints `1 1 CLAUDE.md`, `1 1 home/common/claude-code/README.md`, `8 6 home/common/claude-code/lifecycle_guard.py` and `4 3 tests/test_claude_permission_guard.py`, separated by tabs. A scratch trial of these exact texts gave this result.

- [ ] **Step 5: Commit the rewording**

```bash
git add CLAUDE.md home/common/claude-code/lifecycle_guard.py home/common/claude-code/README.md tests/test_claude_permission_guard.py
launch-commit … -- -m "docs(gh): the keyring credential is the authority, not a shell token (#399)" \
  -m "Comment and prose only; every token scrub and the sanctioned prefix are unchanged." \
  -m "<session trailers>"
```

- [ ] **Step 6: Suites at the commit**

Save as `<scratch>/i399/guard-suite.sh` (the guard-suite invocation):

```bash
#!/usr/bin/env bash
set -euo pipefail
# Full logs stay in the log dir; a failing step prints its whole log, a passing one its tail.
LOG="${1:?usage: guard-suite.sh <log dir>}"; mkdir -p "$LOG"
run_logged() { local name=$1; shift; if ! "$@" >"$LOG/$name.log" 2>&1; then cat "$LOG/$name.log"; echo "$name failed; full log: $LOG/$name.log"; exit 1; fi; }
run_logged build just build
tail -3 "$LOG/build.log"
REQ=$(nix-store --query --requisites ./result)
SETTINGS=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$')
BASE=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$')
test "$(printf '%s\n' "$SETTINGS" | wc -l)" -eq 1
test "$(printf '%s\n' "$BASE" | wc -l)" -eq 1
run_logged guard-suite env CLAUDE_SETTINGS_PATH="$SETTINGS" CLAUDE_GUARD_BASE_POLICY_PATH="$BASE" \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py
tail -4 "$LOG/guard-suite.log"
```

With a clean tree, run (timeout 1200 s, or 3600 s when the build is cold): `launch-scope exec … -- bash <scratch>/i399/guard-suite.sh <scratch>/i399/logs`. Expected: exit 0, ending in `Ran <n> tests in <t>s` and `OK`. A failure here comes from the build or the suite, not from the comment text: report it with the failing lines and do not edit any assertion.

Run (timeout 300 s): `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py > <scratch>/i399/logs/shell-contracts.log 2>&1`, then `tail -3` that log (print the whole log when the exit is non-zero). Expected: exit 0 and `OK (skipped=1)` (34 tests at the base).

Run `bash <scratch>/i399/task2-check.sh` once more at the commit. Expected: `AC5: zero matches (git grep exit 1)`, exit 0.

- [ ] **Step 7: Fill AC4 and AC5 in the acceptance record**

In `.agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md`, replace the `—` in these columns. Leave every other cell and every `Verdict` alone:
- `AC4`: `Observed` holds the guard suite's `Ran <n> tests …` and `OK` lines, the `test_shell_example_contracts.py` result, and `just agent-workflow-tests in final verification`. `Commit` is the short SHA of Step 5's commit. `Conditions` says the suite ran against the build of that commit (`CLAUDE_SETTINGS_PATH` and `CLAUDE_GUARD_BASE_POLICY_PATH` from `./result`). It also says the recipe does not contain the guard suite, which is why it ran separately (D7).
- `AC5`: `Observed` holds `zero matches (git grep exit 1)`. `Commit` is the same SHA. `Conditions` says the pathspec was `CLAUDE.md home python` and that `.agents/artifacts/` is exempt by the criterion.

- [ ] **Step 8: Commit the record**

```bash
git add .agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record, AC4 and AC5 evidence (#399)" -m "<session trailers>"
```

Verify: `git status --short` prints nothing. The `AC4` and `AC5` rows of the record show no `—` in `Observed`, and `grep -c '^| AC[1-7] |'` on the record still prints `7`.
