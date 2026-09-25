# Task 3: Demonstrate the acceptance table

Decisions: D1, D3, D7, D8, D12, D13. Spec section "Test seams", the
demonstration table. This task is verification only. It commits nothing, and
every temporary edit is reverted before it finishes. Work from the worktree
root. Every shell block starts with these lines, which the blocks below omit:

```bash
set -euo pipefail
CAP="${TMPDIR:-/tmp}"; CAP="${CAP%/}/issue-176"
N=home/common/claude-code/default.nix
G=home/common/claude-code/lifecycle_guard.py
```

**Files:** none are committed. `home/common/claude-code/default.nix` is edited
twice, temporarily (Steps 4 and 8), and restored with
`git checkout -- home/common/claude-code/default.nix`.

**Interfaces:**
- Consumes: the states Tasks 1 and 2 committed, and
  `$CAP/{base-sha,base-settings.json,base-guard.py}` from Task 1, Step 1.
- Produces: the acceptance evidence, reported as each step's printed markers.
  Nothing is written outside `$CAP`.

**Invariants:**
- Each demonstration row prints its marker. A missing marker is a failed
  acceptance criterion: report it, and do not patch the code in this task.
- The worktree ends clean: `git status --porcelain` prints nothing, and
  `git diff --quiet HEAD` holds.

- [ ] **Step 1: Preconditions, and regenerating the base if it is gone**

```bash
git status --porcelain | { if read -r _; then echo "worktree not clean" >&2; exit 1; fi; }
if [ ! -s "$CAP/base-settings.json" ] || [ ! -s "$CAP/base-guard.py" ]; then
  test -s "$CAP/base-sha"
  rm -rf "$CAP/base-tree"; mkdir -p "$CAP/base-tree"
  git archive "$(cat "$CAP/base-sha")" | tar -x -C "$CAP/base-tree"
  (cd "$CAP/base-tree" && git init -q && git add -A && just show-claude-settings) > "$CAP/base-settings.json"
  cat "$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$CAP/base-settings.json")" > "$CAP/base-guard.py"
fi
head -n1 "$CAP/base-guard.py" | grep -q '^#!/nix/store/.*/bin/python3$' && echo base-ok
just show-claude-settings > "$CAP/final-settings.json" 2> "$CAP/final-build.log"
jq '.hooks.PreToolUse' "$CAP/final-settings.json"
```

Expected: `base-ok`, then a one-element array. Its matcher is `"Bash"`, and it
holds one hook with `"type": "command"`, `"timeout": 30`, no `args`, and a
`command` of the form `/nix/store/<hash>-claude-bash-lifecycle-guard/bin/claude-bash-lifecycle-guard`.
Base builds are content-addressed, so a regenerated base yields the same store
paths.

- [ ] **Step 2: Acceptance 1, the source is its own file**

```bash
test -f "$G" && echo source-file-ok
if grep -nE '^\s*(import|from|def|class) ' "$N"; then exit 1; fi
git show "$(cat "$CAP/base-sha")":"$N" | grep -cE '^\s*(import|from|def|class) '
```

Expected: `source-file-ok`, no grep output, then `33`, the base count, all of
which sat inside the guard.

- [ ] **Step 3: Acceptance 2, no interpolation**

```bash
if grep -nE '\$\{|/nix/store|fagenorn|elevenyellow|nodocom|arcwave' "$G"; then exit 1; fi
echo no-interpolation-ok
```

Expected: `no-interpolation-ok`.

- [ ] **Step 4: Acceptance 2, an owner change touches only the policy**

```bash
trap 'git checkout -- home/common/claude-code/default.nix' EXIT
python3 - "$N" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '    "fagenorn"\n    "elevenyellow"\n  ];\n'
assert text.count(old) == 1, "authorizedOwners block not found"
path.write_text(text.replace(old, '    "fagenorn"\n    "elevenyellow"\n    "demo-owner"\n  ];\n'), encoding="utf-8")
PY
git diff --numstat -- "$N"
just show-claude-settings > "$CAP/owner-settings.json" 2> "$CAP/owner-build.log"
git checkout -- "$N"; trap - EXIT
for f in final owner; do
  tail -n1 "$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$CAP/$f-settings.json")" \
    | tr ' ' '\n' | grep '^/nix/store/' > "$CAP/$f-exec.txt"
  cat "$(sed -n 3p "$CAP/$f-exec.txt")"; echo
done
cmp <(sed -n 1,2p "$CAP/final-exec.txt") <(sed -n 1,2p "$CAP/owner-exec.txt") && echo source-path-unchanged
if cmp -s <(sed -n 3p "$CAP/final-exec.txt") <(sed -n 3p "$CAP/owner-exec.txt"); then exit 1; fi
diff <(jq . "$(sed -n 3p "$CAP/final-exec.txt")") <(jq . "$(sed -n 3p "$CAP/owner-exec.txt")") || true
```

Expected: `1	0	home/common/claude-code/default.nix`. Next come the two
policy documents; the second one also lists `demo-owner`. Then
`source-path-unchanged` prints, meaning the interpreter and the
`-lifecycle_guard.py` store paths are identical. The policy paths differ. The
final diff touches only the owners array: `"elevenyellow"` gains a comma, and
`"demo-owner"` is added.

- [ ] **Step 5: Extraction fidelity, and an unchanged hook shape**

```bash
rc=0; diff -u "$CAP/base-guard.py" "$G" > "$CAP/final-fidelity.diff" || rc=$?; test "$rc" -eq 1
grep -c '^@@' "$CAP/final-fidelity.diff"
grep '^-' "$CAP/final-fidelity.diff" | grep -vc '^---'
for f in base final; do
  jq -S '.hooks | walk(if type=="string" then gsub("/nix/store/[0-9a-z]{32}-";"/nix/store/HASH-") else . end)' \
    "$CAP/$f-settings.json" > "$CAP/$f-hooks.json"
done
diff "$CAP/base-hooks.json" "$CAP/final-hooks.json" && echo hook-shape-ok
```

Expected: `12` hunks and `22` removed lines. These are the E1–E6 edits that
Task 1, Step 9 checked line by line. Then `hook-shape-ok`.

- [ ] **Step 6: The source byte-compiles**

```bash
PYTHONPYCACHEPREFIX="$CAP/pyc" python3 -m py_compile "$G" && echo compiled
```

Expected: `compiled`.

- [ ] **Step 7: The source lints (D13)**

```bash
mkdir -p "$CAP/lint"
printf '%s\n' '{ pkgs, ... }: { packages = [ pkgs.ruff ]; }' > "$CAP/lint/devenv.nix"
ABS="$PWD/$G"
(cd "$CAP/lint" && devenv shell -- ruff check --isolated --select E4,E7,E9,F "$ABS") 2>&1 | tail -1
```

Expected: `All checks passed!`

- [ ] **Step 8: The build check can fail (D7)**

```bash
trap 'git checkout -- home/common/claude-code/default.nix' EXIT
python3 - "$N" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '  authorizedOwners = [\n    "fagenorn"\n    "elevenyellow"\n  ];\n'
assert text.count(old) == 1, "authorizedOwners block not found"
path.write_text(text.replace(old, '  authorizedOwners = "fagenorn";\n'), encoding="utf-8")
PY
rc=0; just build > "$CAP/bad-build.log" 2>&1 || rc=$?
git checkout -- "$N"; trap - EXIT
echo "build-exit $rc"
grep -c 'invalid policy: .*authorized_owners must be a list of non-empty strings' "$CAP/bad-build.log"
grep -c 'refused a harmless Bash payload' "$CAP/bad-build.log"
```

Expected: a non-zero `build-exit`, then counts of at least `1` and `1`. The
failure comes from the wrapper's `checkPhase`.

- [ ] **Step 9: The guard suite passes against the built hook, and the tree is clean**

```bash
just show-claude-settings > "$CAP/final-settings.json" 2> "$CAP/final-build.log"
CLAUDE_SETTINGS_PATH="$CAP/final-settings.json" python3 tests/test_claude_permission_guard.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
git status --porcelain | { if read -r _; then echo "worktree not clean" >&2; exit 1; fi; }
git diff --quiet HEAD && echo clean
```

Expected: `Ran 37 tests …`, `OK` and `clean`. Report every step's marker as the
acceptance evidence. There is no commit.
