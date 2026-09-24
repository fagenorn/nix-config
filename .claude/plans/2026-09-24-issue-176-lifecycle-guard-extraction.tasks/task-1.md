# Task 1: Extract the guard behind a store policy and wrapper

Decisions: D1–D9, D12, D13; parent D4, D9, D10. Spec sections "Files", "The
policy file", "The registered executable", "Extracting the source", "Behaviour
on policy defects", "Build-time check" and "Test seams". Work from the worktree
root. Every shell block starts with these lines, which the blocks below omit:

```bash
set -euo pipefail
CAP="${TMPDIR:-/tmp}"; CAP="${CAP%/}/issue-176"
N=home/common/claude-code/default.nix
G=home/common/claude-code/lifecycle_guard.py
```

**Files:**
- Create: `home/common/claude-code/lifecycle_guard.py` (mode `100644`)
- Modify: `home/common/claude-code/default.nix` (the `lifecycleGuard` binding,
  base lines 69–1008, only)
- Test: `tests/test_claude_permission_guard.py` (one appended method)

**Interfaces:**
- Consumes: the base `default.nix`. Its `lifecycleGuard` binding is lines
  69–1008, and the guard text is lines 74–1006, indented six columns.
- Produces:
  - The guard CLI:
    `<wrapper> [--git-bin P] [--gh-bin P] [--jq-bin P] [--child-timeout-seconds S]`.
    It reads hook JSON on stdin and exits 0 to allow or 2 to block. The wrapper
    prepends `--policy <store JSON>`.
  - In the source:
    - `POLICY_KEYS`, a frozenset of the five key names.
    - `class Policy(document)`, with `authorized_owners` (a frozenset of str),
      `integration_bases` (a dict of str to str), and `git_bin`, `gh_bin` and
      `jq_bin` (str).
    - `load_policy(path)`, which returns `(Policy, None)` or `(None, reason)`.
    - `Context(args, policy, cwd)`.
    - `ownership_problem(repository, authorized_owners)` and
      `authorized_bases(repository, base_branch, integration_bases)`.
  - In Nix: `lifecycleGuardPolicy` (the store JSON) and `lifecycleGuard` (the
    wrapper at `/bin/claude-bash-lifecycle-guard`).
  - In `$CAP`, for Task 3: `base-sha`, `base-settings.json`, `base-guard.py` and
    `new-settings.json`.

**Invariants:**
- The lines that `diff -u` of the base built guard against the new file removes
  are exactly the 22 lines listed in Step 9 (D12).
- The source contains no `${`, no `/nix/store`, and no owner or repository name.
  `default.nix` contains no line that starts with `import`, `from`, `def` or
  `class`.
- The wrapper is exactly three lines. The source and policy each have their own
  interpolated store path (D1, D2).
- The generated `.hooks` equals base apart from store hashes, and every other
  settings key is identical to base.
- The policy is read inside `main()`, after the hook-input checks and before
  `guarded_operations`, and never at import time (D4).
- Outside the replaced binding, `default.nix` is byte-identical to base (D6). No
  existing test line changes (D9).

- [ ] **Step 1: Capture the base before any edit**

```bash
git diff --quiet HEAD -- home/common/claude-code tests/test_claude_permission_guard.py
mkdir -p "$CAP"
git rev-parse HEAD > "$CAP/base-sha"
just show-claude-settings > "$CAP/base-settings.json" 2> "$CAP/base-build.log"
cat "$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$CAP/base-settings.json")" > "$CAP/base-guard.py"
head -n1 "$CAP/base-guard.py"
grep -cE '^\s*(import|from|def|class) ' "$N"
```

Expected: `#!/nix/store/<hash>-python3-<version>/bin/python3`, then `33`. If
either differs, stop and report, because the base has moved.

- [ ] **Step 2: Write the failing test**

Append this method to `ClaudePermissionGuardTest`, directly after the last line
of `test_unexpected_dependency_exception_blocks`
(`        self.assertIn("lifecycle guard: unexpected failure:", result.stderr)`),
preceded by one blank line. Keep the two blank lines before
`if __name__ == "__main__":`, and change no other line.

```python
    def test_hostile_interpreter_environment_is_ignored(self):
        # Each plant exits 0 before the guard can judge: a `json` package reached
        # through PYTHONPATH, and a .pth line reached through NIX_PYTHONPATH, which
        # nixpkgs' sitecustomize honours even under -I. Seeing either would turn a
        # refusal into an allow, so the registered hook must ignore both.
        hostile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (hostile / "json").mkdir()
        (hostile / "json" / "__init__.py").write_text(
            "import os\nos._exit(0)\n", encoding="utf-8"
        )
        (hostile / "hostile.pth").write_text("import os; os._exit(0)\n", encoding="utf-8")
        result = self.invoke_command(
            "git branch -d -f topic",
            env={"PYTHONPATH": str(hostile), "NIX_PYTHONPATH": str(hostile)},
        )
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("lifecycle guard: unsafe branch deletion:", result.stderr)
```

- [ ] **Step 3: Run it against the base hook and watch it fail**

```bash
git diff --numstat -- tests/test_claude_permission_guard.py
out="$(CLAUDE_SETTINGS_PATH="$CAP/base-settings.json" python3 tests/test_claude_permission_guard.py 2>&1 || true)"
printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: `18	0	tests/test_claude_permission_guard.py`, then
`FAIL: test_hostile_interpreter_environment_is_ignored (…)`, `Ran 37 tests …` and
`FAILED (failures=1)`. The shadowed `json` makes the base guard exit 0.

- [ ] **Step 4: Extract the source verbatim**

```bash
test "$(sed -n 69p "$N")" = "  lifecycleGuard = pkgs.writeTextFile {"
test "$(sed -n 73p "$N")" = "    text = ''"
test "$(sed -n 1007p "$N")" = "    '';"
test "$(sed -n 1008p "$N")" = "  };"
sed -n '74,1006p' "$N" | sed -E 's/^ {6}//' > "$G"
diff "$CAP/base-guard.py" "$G" | grep -c '^[<>]'
```

Expected: `12`. These are the shebang and the five spliced constants on each
side. Nothing else differs.

- [ ] **Step 5: Apply E1–E6 to `lifecycle_guard.py` (D4, D5, D12)**

Each edit replaces exact text. Leave every other line alone.

**E1.** Replace line 1 (`#!${pkgs.python3}/bin/python3`) with these seven lines.
The last one is blank, so `import argparse` follows a blank line:

```python
"""Claude Code's PreToolUse Bash lifecycle guard.

The claude-code module's store wrapper clears NIX_PYTHON* and runs this file
under `python3 -I` with `--policy <store JSON of the Nix-owned values>`.
Standard library only: it imports nothing from agent_tools.
"""

```

**E2.** Replace the five lines that start with `DEFAULT_GIT_BIN =`,
`DEFAULT_GH_BIN =`, `DEFAULT_JQ_BIN =`, `AUTHORIZED_OWNERS =` and
`INTEGRATION_BASES =` with:

```python
POLICY_KEYS = frozenset(
    {"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"}
)
```

**E3.** Insert this immediately before `class Context:`, with two blank lines
before `class Policy:` and two after `return Policy(document), None`. It
enforces the spec's policy shape rules, and the carve-out applies, so write it
exactly:

```python
class Policy:
    """The Nix-owned values, read from the store policy file."""

    def __init__(self, document):
        self.authorized_owners = frozenset(document["authorized_owners"])
        self.integration_bases = dict(document["integration_bases"])
        self.git_bin = document["git_bin"]
        self.gh_bin = document["gh_bin"]
        self.jq_bin = document["jq_bin"]


def load_policy(path):
    """(Policy, None) for a well-formed policy file at `path`, else (None, reason)."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"cannot load {path}: {error}"
    if not isinstance(document, dict) or set(document) != POLICY_KEYS:
        keys = ", ".join(sorted(POLICY_KEYS))
        return None, f"{path}: expected an object with exactly the keys {keys}"
    owners = document["authorized_owners"]
    if not isinstance(owners, list) or not all(
        isinstance(owner, str) and owner for owner in owners
    ):
        return None, f"{path}: authorized_owners must be a list of non-empty strings"
    bases = document["integration_bases"]
    if not isinstance(bases, dict) or not all(
        isinstance(repository, str) and repository and isinstance(base, str) and base
        for repository, base in bases.items()
    ):
        return None, f"{path}: integration_bases must be an object of non-empty strings"
    for key in ("git_bin", "gh_bin", "jq_bin"):
        if not isinstance(document[key], str) or not os.path.isabs(document[key]):
            return None, f"{path}: {key} must be an absolute path"
    return Policy(document), None
```

**E4.** In `Context`, change `    def __init__(self, args, cwd):` to
`    def __init__(self, args, policy, cwd):`. Directly after
`        self.timeout = args.child_timeout_seconds`, insert:

```python
        self.authorized_owners = policy.authorized_owners
        self.integration_bases = policy.integration_bases
```

**E5.** Make these exact replacements:
- `def ownership_problem(repository):` becomes
  `def ownership_problem(repository, authorized_owners):`.
- `    if repository.split("/", 1)[0] not in AUTHORIZED_OWNERS:` becomes
  `    if repository.split("/", 1)[0] not in authorized_owners:`.
- `def authorized_bases(repository, base_branch):` becomes
  `def authorized_bases(repository, base_branch, integration_bases):`.
- In `authorized_bases`, `    integration_base = INTEGRATION_BASES.get(repository)`
  becomes `    integration_base = integration_bases.get(repository)`.
- There are three occurrences, in `validate_push`, `validate_pr_create` and
  `validate_merge`, of `    problem = ownership_problem(context.repository)`.
  Each becomes
  `    problem = ownership_problem(context.repository, context.authorized_owners)`.
- In `validate_pr_create`, `    allowed_bases = authorized_bases(context.repository, context.base_branch)` becomes:

  ```python
      allowed_bases = authorized_bases(
          context.repository, context.base_branch, context.integration_bases
      )
  ```
- In `validate_merge`, the two lines
  `    allowed_bases = authorized_bases(repository, context.base_branch)` and
  `    integration_base = INTEGRATION_BASES.get(repository)` become:

  ```python
      allowed_bases = authorized_bases(
          repository, context.base_branch, context.integration_bases
      )
      integration_base = context.integration_bases.get(repository)
  ```

**E6.** In `main()`, replace the four lines from `    parser = argparse.ArgumentParser()`
through `    parser.add_argument("--jq-bin", default=DEFAULT_JQ_BIN)` with the lines
below. The `--child-timeout-seconds` line stays.

```python
    parser = argparse.ArgumentParser(prog="claude-bash-lifecycle-guard")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--git-bin", default=None)
    parser.add_argument("--gh-bin", default=None)
    parser.add_argument("--jq-bin", default=None)
```

Between the last hook-input check,
`        return block("invalid hook input: expected tool_input.command to be a string")`,
and its following blank line plus `    context = None`, insert one blank line and
then:

```python
    policy, reason = load_policy(args.policy)
    if policy is None:
        return block(f"invalid policy: {reason}")
    if args.git_bin is None:
        args.git_bin = policy.git_bin
    if args.gh_bin is None:
        args.gh_bin = policy.gh_bin
    if args.jq_bin is None:
        args.jq_bin = policy.jq_bin
```

Then change `                context = Context(args, payload.get("cwd"))` to
`                context = Context(args, policy, payload.get("cwd"))`.

Check: `grep -nE 'DEFAULT_(GIT|GH|JQ)_BIN|AUTHORIZED_OWNERS|INTEGRATION_BASES|\$\{' "$G"`
prints nothing.

- [ ] **Step 6: Replace the Nix binding (D1, D2, D3, D7)**

Write the block with a quoted heredoc, so that `${…}`, `$target` and `"$@"` stay
literal. Splice it over base lines 69–1008. Lines 1–68 and 1009 onward stay
untouched.

```bash
cat > "$CAP/nix-block.txt" <<'NIX'
  # The Nix-owned values the lifecycle guard reads at run time, as one store
  # JSON file. The guard's source never embeds them, so an owner or base change
  # moves only this file, and the tool paths keep git, gh and jq in the closure.
  lifecycleGuardPolicy = pkgs.writeText "claude-bash-lifecycle-guard-policy.json" (
    builtins.toJSON {
      authorized_owners = authorizedOwners;
      integration_bases = integrationBases;
      git_bin = "${pkgs.git}/bin/git";
      gh_bin = "${pkgs.gh}/bin/gh";
      jq_bin = "${pkgs.jq}/bin/jq";
    }
  );

  # The registered hook: one argument-free store path. It runs the guard's own
  # source isolated from PYTHONPATH, user site and NIX_PYTHON* `.pth` hooks, and
  # `exec` lets the hook's timeout kill reach Python rather than orphan it. The
  # check refuses to build a guard that cannot load its source or policy.
  lifecycleGuard = pkgs.writeTextFile {
    name = "claude-bash-lifecycle-guard";
    executable = true;
    destination = "/bin/claude-bash-lifecycle-guard";
    text = ''
      #!${pkgs.runtimeShell}
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      exec ${pkgs.python3}/bin/python3 -I ${./lifecycle_guard.py} --policy ${lifecycleGuardPolicy} "$@"
    '';
    checkPhase = ''
      if ! printf '%s' '{"tool_name":"Bash","tool_input":{"command":"true"}}' | "$target"; then
        echo "claude-bash-lifecycle-guard: refused a harmless Bash payload" >&2
        exit 1
      fi
    '';
  };
NIX
test "$(wc -l < "$CAP/nix-block.txt" | tr -d ' ')" = 33
{ sed -n '1,68p' "$N"; cat "$CAP/nix-block.txt"; sed -n '1009,$p' "$N"; } > "$CAP/default.nix.new"
cat "$CAP/default.nix.new" > "$N"
diff <(git show "$(cat "$CAP/base-sha")":"$N" | sed '69,1008d') <(sed '69,101d' "$N") && echo outside-binding-identical
```

Expected: `outside-binding-identical`. Keep `${./lifecycle_guard.py}`
interpolated. It must never become `builtins.toString` (D1).

- [ ] **Step 7: Build and pass the suite**

```bash
git add "$G"
just show-claude-settings > "$CAP/new-settings.json" 2> "$CAP/new-build.log" || { grep -E 'error|invalid policy|refused' "$CAP/new-build.log" | head -20; exit 1; }
CLAUDE_SETTINGS_PATH="$CAP/new-settings.json" python3 tests/test_claude_permission_guard.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: `Ran 37 tests …` and `OK`. The build already ran `checkPhase`.

- [ ] **Step 8: Show the new case can fail (D2, D9; shown once)**

```bash
W="$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$CAP/new-settings.json")"
mkdir -p "$CAP/variants"
sed 's/ -I / /' "$W" > "$CAP/variants/no-isolation"
sed '/^unset /d' "$W" > "$CAP/variants/no-unset"
for v in no-isolation no-unset; do
  if cmp -s "$W" "$CAP/variants/$v"; then echo "variant $v did not change" >&2; exit 1; fi
  chmod +x "$CAP/variants/$v"
  jq --arg c "$CAP/variants/$v" '.hooks.PreToolUse[0].hooks[0].command = $c' \
    "$CAP/new-settings.json" > "$CAP/variants/$v.json"
  out="$(CLAUDE_SETTINGS_PATH="$CAP/variants/$v.json" python3 tests/test_claude_permission_guard.py \
    ClaudePermissionGuardTest.test_hostile_interpreter_environment_is_ignored 2>&1 || true)"
  printf '%s: %s\n' "$v" "$(printf '%s\n' "$out" | grep -E '^(OK|FAILED)')"
done
```

Expected: `no-isolation: FAILED (failures=1)` and
`no-unset: FAILED (failures=1)`. Without `-I` the shadowed `json` wins.
Without the `unset`, the `.pth` line runs even under `-I`.

- [ ] **Step 9: Verify fidelity, shape, wrapper and policy**

```bash
W="$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$CAP/new-settings.json")"
P="$(sed -n 's/.* --policy \([^ ]*\) .*/\1/p' "$W")"
rc=0; diff -u "$CAP/base-guard.py" "$G" > "$CAP/fidelity.diff" || rc=$?; test "$rc" -eq 1
grep '^-' "$CAP/fidelity.diff" | grep -v '^---' | sed -E 's#/nix/store/[^" ]+#STORE#g' > "$CAP/removed.txt"
cat > "$CAP/expected-removed.txt" <<'EOF'
-#!STORE
-DEFAULT_GIT_BIN = "STORE"
-DEFAULT_GH_BIN = "STORE"
-DEFAULT_JQ_BIN = "STORE"
-AUTHORIZED_OWNERS = frozenset({"fagenorn", "elevenyellow"})
-INTEGRATION_BASES = {"elevenyellow/nodocom": "dev", "fagenorn/arcwave": "dev"}
-    def __init__(self, args, cwd):
-def ownership_problem(repository):
-    if repository.split("/", 1)[0] not in AUTHORIZED_OWNERS:
-def authorized_bases(repository, base_branch):
-    integration_base = INTEGRATION_BASES.get(repository)
-    problem = ownership_problem(context.repository)
-    problem = ownership_problem(context.repository)
-    allowed_bases = authorized_bases(context.repository, context.base_branch)
-    problem = ownership_problem(context.repository)
-    allowed_bases = authorized_bases(repository, context.base_branch)
-    integration_base = INTEGRATION_BASES.get(repository)
-    parser = argparse.ArgumentParser()
-    parser.add_argument("--git-bin", default=DEFAULT_GIT_BIN)
-    parser.add_argument("--gh-bin", default=DEFAULT_GH_BIN)
-    parser.add_argument("--jq-bin", default=DEFAULT_JQ_BIN)
-                context = Context(args, payload.get("cwd"))
EOF
diff "$CAP/expected-removed.txt" "$CAP/removed.txt" && echo fidelity-ok
for f in base new; do
  jq -S '.hooks | walk(if type=="string" then gsub("/nix/store/[0-9a-z]{32}-";"/nix/store/HASH-") else . end)' \
    "$CAP/$f-settings.json" > "$CAP/$f-hooks.json"
  jq -S 'del(.hooks)' "$CAP/$f-settings.json" > "$CAP/$f-rest.json"
done
diff "$CAP/base-hooks.json" "$CAP/new-hooks.json" && diff "$CAP/base-rest.json" "$CAP/new-rest.json" && echo shape-ok
test "$(wc -l < "$W" | tr -d ' ')" = 3
sed -n 2p "$W" | grep -qx 'unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE'
sed -n 3p "$W" | grep -Eqx 'exec /nix/store/[0-9a-z]{32}-python3-[^ /]+/bin/python3 -I /nix/store/[0-9a-z]{32}-lifecycle_guard\.py --policy /nix/store/[0-9a-z]{32}-claude-bash-lifecycle-guard-policy\.json "\$@"'
jq -c 'del(.git_bin, .gh_bin, .jq_bin)' "$P"
for k in git gh jq; do
  K="$(printf '%s' "$k" | tr a-z A-Z)"
  base="$(sed -n "s/^DEFAULT_${K}_BIN = \"\(.*\)\"\$/\1/p" "$CAP/base-guard.py")"
  test -n "$base"; test "$(jq -r --arg k "${k}_bin" '.[$k]' "$P")" = "$base"
done
if grep -nE '^\s*(import|from|def|class) ' "$N"; then exit 1; fi
if grep -nE '\$\{|/nix/store|fagenorn|elevenyellow|nodocom|arcwave' "$G"; then exit 1; fi
git ls-files -s "$G" | cut -c1-6
echo all-ok
```

Expected: `fidelity-ok` and `shape-ok`. The policy line is
`{"authorized_owners":["fagenorn","elevenyellow"],"integration_bases":{"elevenyellow/nodocom":"dev","fagenorn/arcwave":"dev"}}`.
Then come `100644` and `all-ok`. A removed line that is not in the list is an
edit outside E1–E6: undo it.

- [ ] **Step 10: Show the policy-defect table (D3, D4; shown once)**

```bash
W="$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$CAP/new-settings.json")"
P="$(sed -n 's/.* --policy \([^ ]*\) .*/\1/p' "$W")"
PY="$(sed -n 's/^exec \([^ ]*\) .*/\1/p' "$W")"
D="$CAP/defects"; mkdir -p "$D"; ok='{"tool_name":"Bash","tool_input":{"command":"true"}}'
jq -c '.authorized_owners="fagenorn"' "$P" > "$D/owner-string.json"
jq -c '.authorized_owners=["fagenorn",""]' "$P" > "$D/owner-empty.json"
jq -c '.integration_bases={"x/y":""}' "$P" > "$D/base-empty.json"
jq -c '.git_bin="git"' "$P" > "$D/relative-bin.json"
jq -c '. + {"extra": 1}' "$P" > "$D/extra-key.json"
jq -c 'del(.jq_bin)' "$P" > "$D/missing-key.json"
printf '[]' > "$D/not-object.json"; printf '{' > "$D/malformed.json"; printf '\377' > "$D/not-utf8.json"
rm -f "$D/absent.json"
for f in owner-string owner-empty base-empty relative-bin extra-key missing-key not-object malformed not-utf8 absent; do
  rc=0; printf '%s' "$ok" | "$PY" -I "$G" --policy "$D/$f.json" >/dev/null 2>"$D/$f.err" || rc=$?
  echo "$f $rc $(grep -c 'lifecycle guard: invalid policy:' "$D/$f.err")"
done
rc=0; printf '%s' "$ok" | "$PY" -I "$G" --policy "$P" || rc=$?; echo "valid $rc"
rc=0; printf 'not-json' | "$PY" -I "$G" --policy "$D/malformed.json" 2>"$D/input.err" || rc=$?
echo "input-first $rc $(grep -c 'lifecycle guard: invalid hook input:' "$D/input.err")"
rc=0; "$PY" -I "$G" </dev/null 2>"$D/usage.err" || rc=$?
echo "no-policy $rc $(grep -c '^usage: claude-bash-lifecycle-guard' "$D/usage.err")"
```

Expected: ten lines of the form `<name> 2 1`, then `valid 0`, `input-first 2 1`
and `no-policy 2 1`.

- [ ] **Step 11: Byte-compile and lint (D8, D13)**

```bash
PYTHONPYCACHEPREFIX="$CAP/pyc" python3 -m py_compile "$G" && echo compiled
mkdir -p "$CAP/lint"
printf '%s\n' '{ pkgs, ... }: { packages = [ pkgs.ruff ]; }' > "$CAP/lint/devenv.nix"
ABS="$PWD/$G"
(cd "$CAP/lint" && devenv shell -- ruff check --isolated --select E4,E7,E9,F "$ABS") 2>&1 | tail -1
```

Expected: `compiled`, then `All checks passed!`. Do not use plain default rules
or `devenv -O packages:pkgs` (D13).

- [ ] **Step 12: Commit**

```bash
git status --porcelain
git add "$G" "$N" tests/test_claude_permission_guard.py
git commit -m "refactor(claude-code): run the lifecycle guard from its own source and a store policy"
```

`git status --porcelain` lists only the three task files, and no `result`,
capture or `__pycache__` file. The commit message ends with the plan's trailer
lines.
