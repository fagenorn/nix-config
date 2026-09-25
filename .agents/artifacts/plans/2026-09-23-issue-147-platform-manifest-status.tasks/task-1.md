# Task 1: Replay the nine reviewed Task 1–3 commits with provenance

This task moves reviewed code; it writes none. Its tests arrive inside the picks, so
the test-first steps are replaced by provenance and suite gates. Per D1, D2 and D3.

**Files** (every change arrives through a pick):
- Create: `home/common/agent-skills/platform-manifest.json`,
  `home/common/agent-skills/scripts/agent_platform.py`,
  `home/common/agent-skills/tests/test_resolve_platform.py`,
  `home/common/agent-skills/tests/test_resolve_platform_status.py`
- Modify: `.agents/project.json`, `home/common/agent-skills/default.nix`,
  `home/common/agent-skills/scripts/resolve-project.py`,
  `home/common/agent-skills/tests/test_resolve_project.py`
- Modify: `justfile` (the one conflict, resolved by hand)

**Interfaces:**
- Consumes: the retained commits, which are reachable in this repository's object
  store through the local branch `worktree-issue-121-adoption-v1`. Never check out,
  rebase or modify that branch or its worktree.
- Produces, for Task 2 (all recovered verbatim):
  - In `scripts/resolve-project.py`:
    - `bootstrap_platform_library() -> bool`, which binds the module global
      `agent_platform` from `$HOME/.agents/lib/python`;
    - `PLATFORM_LIBRARY_REPAIR_ID == "platform.library.missing"`;
    - `require_platform_manifest() -> tuple[dict, Path]`, which raises
      `ContractError("resolver_failure", <platform.manifest.* id>, violations)`;
    - `validate_schema_version(source, violations, supported)`, which raises
      `unsupported_schema` with reason `project_schema_unsupported`;
    - `validate_contract(source, manifest) -> list[dict]`;
    - `raise_for_platform_range(platform, platform_version)`, which raises
      `ContractError("unsupported_schema", …, reason_code="platform_too_old" | "platform_too_new")`;
    - `declared_facts(source) -> {"project_id", "project_schema_version", "platform_interval"}`;
    - `ContractError.reason_code`.
  - In `tests/test_resolve_project.py`: `install_home(home, manifest=COMMITTED, *, library=True) -> Path`,
    `COMMITTED`, `MANIFEST` and `mutated_manifest(**changes) -> dict`.
  - The committed contract gains
    `"platform": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}`.
  - The committed manifest has `platform_version` `"1.0.0"` and
    `project_schema_versions` `[1]`.
  - `default.nix` publishes `.agents/lib/python/agent_platform.py` and
    `.agents/share/platform-manifest.json`.

**Invariants:**
- Exactly nine new commits, in source order. Each has its source's author, and its
  message is the source message plus one `(cherry picked from commit <full sha>)`
  line. Each commit is signed.
- The `-U0` patch-id of every pick equals its source's, which proves verbatim
  replay. That includes `a74c4d7a`: the two suite lines it adds are its only
  `justfile` change.
- The `agent-workflow-tests` recipe keeps `main`'s list. It lists
  `test_resolve_platform.py`, then `test_resolve_platform_status.py`, immediately
  after `test_resolve_project.py`, and has no `test_adopt_` line.
- Outside `.claude/`, the branch changes exactly the nine files above.

- [ ] **Step 1: Confirm the starting state (each line must hold, or stop)**

```bash
set -euo pipefail
git merge-base --is-ancestor 4f74c47742b4dcebd37edb2e49a4cc227cc53238 HEAD
for c in 862547dd afa5ceba 15a20e53 363c2c7d d87253f2 b2202040 e4cd1d6c a74c4d7a 8e6f0681; do
  git cat-file -e "$c^{commit}"; done
if test -e home/common/agent-skills/scripts/agent_platform.py; then echo "already replayed"; exit 1; fi
test -z "$(git status --porcelain)"
```

- [ ] **Step 2: Replay the commits**

Run: `git cherry-pick -x 862547dd afa5ceba 15a20e53 363c2c7d d87253f2 b2202040 e4cd1d6c a74c4d7a 8e6f0681`

Expected: seven picks commit. The run then stops at `a74c4d7a` with
`CONFLICT (content): Merge conflict in justfile`, which is the only expected
conflict. Any other conflict, or a signing error, means you must run
`git cherry-pick --abort`, stop, and report BLOCKED with the output. Do not disable
signing, and do not edit anything else.

- [ ] **Step 3: Resolve the `justfile` conflict and finish**

Replace the whole conflict block, from `<<<<<<<` to `>>>>>>>`, with `main`'s three
conformance lines, preceded by the two platform suites. The recipe then reads, at
that point:

```
    home/common/agent-skills/tests/test_resolve_project.py \
    home/common/agent-skills/tests/test_resolve_platform.py \
    home/common/agent-skills/tests/test_resolve_platform_status.py \
    home/common/agent-skills/tests/test_conformance.py \
    home/common/agent-skills/tests/test_conformance_checks.py \
    home/common/agent-skills/tests/test_conformance_registry.py \
```

Then run `git add justfile && GIT_EDITOR=true git cherry-pick --continue`. This keeps
the source message verbatim, and `8e6f0681` applies cleanly after it. Confirm with
`git status --porcelain` (empty) and `git log --oneline -10`.

- [ ] **Step 4: Verify provenance and the boundary**

```bash
set -euo pipefail
BASE=$(git merge-base HEAD origin/main)
BASE="$BASE" python3 - <<'EOF'
import os, subprocess
BASE = os.environ["BASE"]
SOURCES = ("862547dd afa5ceba 15a20e53 363c2c7d d87253f2 "
           "b2202040 e4cd1d6c a74c4d7a 8e6f0681").split()
def git(*args, inp=None):
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True, input=inp).stdout
def patch_id(commit):
    diff = git("diff", "-U0", f"{commit}^", commit)
    return git("patch-id", "--stable", inp=diff).split()[0]
picks = [c for c in git("rev-list", "--reverse", "--no-merges", f"{BASE}..HEAD",
                        "^origin/main").split()
         if "(cherry picked from commit " in git("show", "-s", "--format=%B", c)]
assert len(picks) == 9, f"expected 9 picks, found {len(picks)}"
for source, pick in zip(SOURCES, picks):
    full = git("rev-parse", source).strip()
    meta = lambda c: git("show", "-s", "--format=%an <%ae>%n%B", c).rstrip("\n")
    assert meta(pick) == f"{meta(full)}\n(cherry picked from commit {full})", source
    assert "\ngpgsig " in git("cat-file", "commit", pick).split("\n\n", 1)[0], f"{pick} unsigned"
    assert patch_id(pick) == patch_id(full), f"{source} not replayed verbatim"
print("provenance ok")
EOF
python3 - <<'EOF'
import re, pathlib
recipe = pathlib.Path("justfile").read_text().split("agent-workflow-tests:\n", 1)[1].split("\n\n", 1)[0]
suites = re.findall(r"\S+\.py", recipe)
t = "home/common/agent-skills/tests/"
i = suites.index(t + "test_resolve_project.py")
assert suites[i + 1:i + 3] == [t + "test_resolve_platform.py", t + "test_resolve_platform_status.py"], suites[i:i + 3]
assert not [s for s in suites if "test_adopt_" in s] and len(suites) == len(set(suites))
print("justfile ok")
EOF
git diff --name-only "$BASE" HEAD -- . ':(exclude).claude/' | sort > "${TMPDIR:-/tmp}/t1-files.txt"
printf '%s\n' .agents/project.json home/common/agent-skills/default.nix \
  home/common/agent-skills/platform-manifest.json home/common/agent-skills/scripts/agent_platform.py \
  home/common/agent-skills/scripts/resolve-project.py home/common/agent-skills/tests/test_resolve_platform.py \
  home/common/agent-skills/tests/test_resolve_platform_status.py \
  home/common/agent-skills/tests/test_resolve_project.py justfile | sort | diff - "${TMPDIR:-/tmp}/t1-files.txt"
```

Expected: `provenance ok`, `justfile ok`, and no diff output. Before Step 2, the first
assertion fails with `expected 9 picks, found 0`.

- [ ] **Step 5: Verify the suites**

Run:
`python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py home/common/agent-skills/tests/test_resolve_platform_status.py 2>&1 | tail -3`

Expected: `Ran 178 tests` and `OK`.

Run: `L="${TMPDIR:-/tmp}/t1-awt.log"; just agent-workflow-tests > "$L" 2>&1; grep -E '^(Ran [0-9]+ tests|OK|FAILED)' "$L"; grep -E '^(FAIL|ERROR): ' "$L" | grep -vE '\.test_conformance(_checks|_registry)?\.' || echo "no failures outside conformance"`

Expected, and known per D1: `Ran 994 tests`, then `FAILED (failures=50, errors=8)`, with every failure
inside the three conformance suites, followed by `no failures outside conformance`.
The suite takes about 3 minutes. Any failure line printed by the `grep` is a stop.
Task 2 turns the conformance suites green.

- [ ] **Step 6: No commit to write**

The picks are the commits. Leave the tree clean (`git status --porcelain` is empty)
and report the nine new SHAs with their sources.
