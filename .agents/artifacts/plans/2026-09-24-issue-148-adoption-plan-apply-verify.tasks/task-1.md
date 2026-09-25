# Task 1: Replay the nine Task 4–6 commits and prove them on the built generation

This task moves reviewed code and writes none. Its tests arrive inside the picks,
so the test-first steps are replaced by provenance, suite, build and run gates.
Per D1–D5 and D10.

**Files** (every change arrives through a pick; `S=home/common/agent-skills`):
- Create: `S/scripts/adopt-project.py`, `S/scripts/adopt_inspection.py`,
  `S/scripts/adopt_planning.py`, `S/scripts/adopt_apply.py`,
  `S/scripts/adopt_verify.py`, `S/tests/test_adopt_project.py`,
  `S/tests/test_adopt_project_boundaries.py`, `S/tests/test_adopt_apply.py`,
  `S/tests/test_adopt_verify.py`
- Modify: `S/scripts/agent_platform.py` (the registry writer and lock, pick 5),
  `S/default.nix` and `justfile` (the pick-1 conflict, resolved by script)
- Modify, docstring only, in one commit of its own (Step 3a, per D11):
  `S/tests/test_resolve_project.py`, `S/tests/test_resolve_platform_status.py`

**Interfaces:**
- Consumes: the retained commits, reachable in this repository's object store
  through the local branch `worktree-issue-121-adoption-v1`. Also the landed #147
  foundation on the base: `agent_platform.load_manifest`, `state_root`,
  `ensure_directory`, the registry reader, and `resolve-project platform-status --fleet`.
- Produces (recovered verbatim, no later task):
  - `$HOME/.agents/bin/adopt-project` with `plan --repo-root PATH [--format json|human]`,
    `apply --plan-id sha256:<64 hex> [--acknowledge-deletions]`, and
    `verify --repo-root PATH [--register]`;
  - `apply` success JSON with members `branch` (`adopt-<first 12 hex of the digest>`),
    `commit`, `plan_id`, `migration_map` and `evidence_record`;
  - refusals as `{"error": {"code", "repair_id", "violations"}}` on exit 2, among
    them `plan_stale`/`adopt.plan.inputs_changed`, `plan_not_found`, `not_ready`
    and `not_integrated`;
  - `$HOME/.agents/state/fleet/registry.json` =
    `{"schema_version": 1, "projects": [{"project_id", "root"}, …]}`, which is
    written only by `verify --register`;
  - `default.nix` installs `.agents/bin/adopt-project` (executable) and the four
    `.agents/lib/python/adopt_{inspection,planning,apply,verify}.py` libraries.

**Invariants:**
- Exactly nine new commits, in source order. Each has its source's author, and its
  message is the source message plus one `(cherry picked from commit <full sha>)`
  line. Each commit is signed.
- The `-U0` patch-id of every pick equals its source's, which proves a verbatim
  replay. That includes the conflicted `08c9caf0`.
- The `agent-workflow-tests` list is the base's list with the four adoption
  suites inserted, in the order `test_adopt_project`,
  `test_adopt_project_boundaries`, `test_adopt_apply`, `test_adopt_verify`,
  immediately after `test_conformance_registry.py`.
- In `default.nix`, the `adopt-project` binary entry sits between the
  `conformance-checks` and `agent-model-matrix` entries. The four library entries
  follow `platform-manifest.json`. Neither file loses a line.
- Outside `.claude/`, the branch changes exactly the fourteen files above: the
  twelve slice files and the two D11 docstring files.
- The run leaves the operator's `~/.agents/state/fleet/` (registry and lock) and
  `~/.agents/state/adopt/` byte-identical, or equally absent.

**If a gate fails (D3, D10).** Never amend, rebase, re-pick or hand-edit a pick. A
failure that the slice does not cause stops the task, and you report BLOCKED with
the failing lines. That covers a test that also fails on the base, and a host,
network or Nix-store condition. For a failure that the slice causes, take these
steps in one new commit after the nine picks:
1. Add the failing case to the sibling suite that owns the verb:
   `test_adopt_project_boundaries` for plan and inspection, `test_adopt_apply`,
   or `test_adopt_verify`. Never add it to `test_adopt_project.py`.
2. Run that case and watch it fail.
3. Make the minimal fix in the slice file that owns the behaviour.
4. Re-run Steps 4–7. The counts in Steps 5 and 6 grow by the cases you added.
5. Commit only the files you touched, as `fix(agent-skills): <what the gate
   proved>`. The body names the failing gate and ends in the two lines from the
   plan root.

A fix that needs a file outside the twelve, or that widens a closed vocabulary or
an output shape, is reported BLOCKED instead.

- [ ] **Step 1: Confirm the starting state (each line must hold, or stop)**

```bash
set -euo pipefail
git merge-base --is-ancestor 185cc1a46668faf960be605734b6136d9234e245 HEAD
for c in 08c9caf0 72b47ae2 c31d64e1 4fdbb8c6 36275eb6 d70a08ef 03c08ffe 44afaa06 11b1e9bc; do
  git cat-file -e "$c^{commit}"; done
if test -e home/common/agent-skills/scripts/adopt-project.py; then echo "already replayed"; exit 1; fi
test -z "$(git status --porcelain)"
```

- [ ] **Step 2: Replay the commits**

Run: `git cherry-pick -x 08c9caf0 72b47ae2 c31d64e1 4fdbb8c6 36275eb6 d70a08ef 03c08ffe 44afaa06 11b1e9bc`

Expected: the run stops at once, at `08c9caf0`, with `CONFLICT (content)` in
`home/common/agent-skills/default.nix` and in `justfile`. Those are the only
expected conflicts. Any other conflict or a signing error means you run
`git cherry-pick --abort`, stop, and report BLOCKED with the output. Do not
disable signing.

- [ ] **Step 3: Resolve pick 1 as a union and finish (D1)**

Each file holds one conflict block whose base section is empty. The script
keeps main's side, then appends the pick's side, and refuses any other shape.

```bash
set -euo pipefail
python3 - <<'EOF'
import re, pathlib
pat = re.compile(r"^<<<<<<< [^\n]*\n(.*?)(?:^\|\|\|\|\|\|\| [^\n]*\n(.*?))?"
                 r"^=======\n(.*?)^>>>>>>> [^\n]*\n", re.M | re.S)
for name in ("home/common/agent-skills/default.nix", "justfile"):
    p = pathlib.Path(name); text = p.read_text()
    blocks = pat.findall(text)
    assert len(blocks) == 1 and not blocks[0][1], (name, blocks)
    text = pat.sub(lambda m: m.group(1) + m.group(3), text)
    assert not re.search(r"^(<{7}|={7}|>{7}|\|{7})", text, re.M), name
    p.write_text(text)
print("union ok")
EOF
git add home/common/agent-skills/default.nix justfile
GIT_EDITOR=true git cherry-pick --continue
test -z "$(git status --porcelain)"; git log --oneline -12
```

Expected: `union ok`. Then the eight remaining picks apply cleanly, and the log
shows nine picks above the spec and plan commits. A new conflict is a stop: run
`git cherry-pick --abort` and report BLOCKED.

- [ ] **Step 3a: Point the two registry-reader docstrings at the landed writer (D11)**

Pick 5 lands the registry writer, so two base docstrings stop being true: they
still say "Task 6 owns the writer" and that the writer does not exist yet. This
step rewrites only those clauses, and the AST check refuses anything that is not
a docstring change.

```bash
set -euo pipefail
python3 - <<'EOF'
import ast, pathlib, subprocess
T = "home/common/agent-skills/tests/"
EDITS = {
    T + "test_resolve_project.py": (
        "(D18). Task 6 owns the writer; the suite\n"
        "    stages this file by hand so the read side can be exercised before it\n"
        "    exists.\n",
        "(D18). `adopt-project verify --register`\n"
        "    writes it; the suite stages this file by hand so the read side is\n"
        "    exercised apart from its writer.\n"),
    T + "test_resolve_platform_status.py": (
        "    The registry is staged by hand here: Task 6 owns the writer, and this\n"
        "    subcommand adds only the reader.\n",
        "    The registry is staged by hand here, apart from its writer\n"
        "    (`adopt-project verify --register`); this subcommand only reads it.\n"),
}
def code_only(src):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body[0].value.value = ""
    return ast.dump(tree)
for name, (old, new) in EDITS.items():
    path = pathlib.Path(name); text = path.read_text()
    assert text.count(old) == 1, name
    path.write_text(text.replace(old, new))
    before = subprocess.run(["git", "show", f"HEAD:{name}"], check=True,
                            capture_output=True, text=True).stdout
    assert code_only(before) == code_only(path.read_text()), f"{name}: not docstring-only"
print("docstrings ok")
EOF
git add home/common/agent-skills/tests/test_resolve_project.py \
  home/common/agent-skills/tests/test_resolve_platform_status.py
git commit -F - <<'EOF'
docs(agent-skills): point the registry-reader docstrings at the landed writer

The replayed Task 4-6 slice adds agent_platform.write_registry, reached
through adopt-project verify --register, so the two reader docstrings that
said the writer did not exist yet now name it. Docstring-only (spec D11).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XJQu22Bg2fayzv7KNKKbaA
EOF
test -z "$(git status --porcelain)"
```

Expected: `docstrings ok`, then one signed commit that changes 5 lines in each
direction across the two files. An assertion failure stops the step. In that
case, restore the two files with `git checkout -- <file>` and report BLOCKED.

- [ ] **Step 4: Verify provenance, wiring and the boundary**

```bash
set -euo pipefail
BASE=$(git merge-base HEAD origin/main)
BASE="$BASE" python3 - <<'EOF'
import os, re, subprocess
BASE = os.environ["BASE"]
SOURCES = ("08c9caf0 72b47ae2 c31d64e1 4fdbb8c6 36275eb6 "
           "d70a08ef 03c08ffe 44afaa06 11b1e9bc").split()
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
def suites(rev):
    recipe = git("show", f"{rev}:justfile").split("agent-workflow-tests:\n", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"\S+\.py", recipe)
t = "home/common/agent-skills/tests/"
adopt = [t + f"test_adopt_{n}.py" for n in ("project", "project_boundaries", "apply", "verify")]
base, head = suites(BASE), suites("HEAD")
i = base.index(t + "test_conformance_registry.py") + 1
assert head == base[:i] + adopt + base[i:], head
nix = git("show", "HEAD:home/common/agent-skills/default.nix")
order = ['".agents/bin/conformance-checks"', '".agents/bin/adopt-project"',
         '".agents/bin/agent-model-matrix"', '".agents/share/platform-manifest.json"',
         '".agents/lib/python/adopt_inspection.py"', '".agents/lib/python/adopt_verify.py"']
at = [nix.index(key) for key in order]
assert at == sorted(at), dict(zip(order, at))
stat = git("diff", "--numstat", BASE, "HEAD", "--", "justfile", "home/common/agent-skills/default.nix")
assert stat.split() == ["15", "0", "home/common/agent-skills/default.nix", "4", "0", "justfile"], stat
print("wiring ok")
EOF
git diff --name-only "$BASE" HEAD -- . ':(exclude).claude/' > "${TMPDIR:-/tmp}/t1-files.txt"
S=home/common/agent-skills
printf '%s\n' $S/default.nix $S/scripts/adopt-project.py $S/scripts/adopt_apply.py \
  $S/scripts/adopt_inspection.py $S/scripts/adopt_planning.py $S/scripts/adopt_verify.py \
  $S/scripts/agent_platform.py $S/tests/test_adopt_apply.py $S/tests/test_adopt_project.py \
  $S/tests/test_adopt_project_boundaries.py $S/tests/test_adopt_verify.py justfile \
  $S/tests/test_resolve_project.py $S/tests/test_resolve_platform_status.py \
  | sort | diff - <(sort "${TMPDIR:-/tmp}/t1-files.txt") && echo "boundary ok"
```

Expected: `provenance ok`, `wiring ok`, `boundary ok`. Before Step 2, the first
assertion fails with `expected 9 picks, found 0`.

- [ ] **Step 5: Verify the focused suites**

Run: `T=home/common/agent-skills/tests; python3 -m unittest $T/test_adopt_project.py $T/test_adopt_project_boundaries.py $T/test_adopt_apply.py $T/test_adopt_verify.py $T/test_resolve_platform.py $T/test_resolve_platform_status.py 2>&1 | tail -3`

Expected: `Ran 221 tests` and `OK`. That is 67 + 14 + 40 + 20 adoption cases and
60 + 20 platform cases. Before Step 2 the command errors, because the adoption
suites do not exist. It takes about 2–4 minutes.

- [ ] **Step 6: Verify the workflow suite**

Run: `L="${TMPDIR:-/tmp}/t1-awt.log"; just agent-workflow-tests > "$L" 2>&1; grep -E '^(Ran [0-9]+ tests|OK|FAILED)' "$L"; grep -E '^(FAIL|ERROR): ' "$L" || echo "no failures"`

Expected, on this base: `Ran 1183 tests`, then `OK (skipped=1)`, then
`no failures`. The count includes the 141 adoption cases, and the run takes about
5–10 minutes. Any `FAIL`/`ERROR` line is a gate failure (see "If a gate fails").

- [ ] **Step 7: Build, and prove the slice on the built generation (D4, D5)**

This step writes an uncommitted driver under `$TMPDIR` (D4). The driver imports
the suites' own fixture builders from this checkout. Every asserted command is a
built binary run as a subprocess under a scratch `HOME`, whose
`.agents/{bin,lib,share}` link into the built tree and whose `.agents/state` is
private. Its numbered comments are the spec's run steps.

```bash
set -euo pipefail
just build
H=$(nix-store -qR ./result | grep -- '-home-manager-files$')
test "$(printf '%s\n' "$H" | wc -l | tr -d ' ')" = 1
D=$(mktemp -d "${TMPDIR:-/tmp}/adopt-demo-XXXXXX"); mkdir "$D/.agents" "$D/.agents/state"
for p in bin lib share; do ln -s "$H/.agents/$p" "$D/.agents/$p"; done
DRV="$D/driver.py"; cat > "$DRV" <<'EOF'
import hashlib, json, os, pwd, subprocess, sys, tempfile
from pathlib import Path
WT, H, D = (Path(os.environ[k]).resolve() for k in ("WT", "H", "D"))
REAL = Path(pwd.getpwuid(os.getuid()).pw_dir)
def operator_state():
    paths = [REAL / ".agents/state/fleet", REAL / ".agents/state/adopt"]
    found = {}
    for p in paths:
        for f in ([p] if p.is_file() else sorted(p.rglob("*")) if p.is_dir() else []):
            found[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "dir"
    return found
BEFORE = operator_state()
os.environ.update(HOME=str(D), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
(D / "fixtures").mkdir(); tempfile.tempdir = str(D / "fixtures")  # removed with D
sys.path.insert(0, str(WT / "home/common/agent-skills/tests"))
from test_adopt_project import bootstrap_repo, commit, git, write
from test_adopt_apply import apply_repo
B = D / ".agents/bin"
def run(tool, *args, code=0):
    p = subprocess.run([str(B / tool), *args], capture_output=True, text=True, timeout=600)
    assert p.returncode == code, (tool, args, p.returncode, p.stdout[-2000:], p.stderr[-2000:])
    return p.stdout
def refusal(out, code, repair=None):
    err = json.loads(out)["error"]
    assert err["code"] == code and (repair is None or err["repair_id"] == repair), err
REGISTRY = D / ".agents/state/fleet/registry.json"
F, G = apply_repo(D), bootstrap_repo(D)
# 1. plan twice: byte-identical, reconcile, ready
first = run("adopt-project", "plan", "--repo-root", str(F))
assert run("adopt-project", "plan", "--repo-root", str(F)) == first, "plan not reproducible"
doc = json.loads(first)
assert (doc["plan"]["outcome"], doc["plan"]["state"]) == ("reconcile", "ready"), doc["plan"]
old_id = doc["plan"]["plan_id"]
# 2. an unrelated commit invalidates the id; stale, unknown and draft ids refuse
write(F, "README.md", "# unrelated\n"); commit(F, "unrelated")
doc = json.loads(run("adopt-project", "plan", "--repo-root", str(F)))
new_id = doc["plan"]["plan_id"]
assert new_id != old_id and doc["plan"]["state"] == "ready", doc["plan"]
refusal(run("adopt-project", "apply", "--plan-id", old_id, code=2), "plan_stale", "adopt.plan.inputs_changed")
refusal(run("adopt-project", "apply", "--plan-id", "sha256:" + "0" * 64, code=2), "plan_not_found")
draft = json.loads(run("adopt-project", "plan", "--repo-root", str(G)))["plan"]
assert draft["state"] == "draft", draft
refusal(run("adopt-project", "apply", "--plan-id", draft["plan_id"], code=2), "not_ready")
# 3. apply: one history-preserving commit on adopt-<12 hex>; HEAD, worktree, registry untouched
base = git(F, "rev-parse", "HEAD").strip()
applied = json.loads(run("adopt-project", "apply", "--plan-id", new_id))
digest, branch = new_id.split(":", 1)[1], applied["branch"]
assert branch == "adopt-" + digest[:12], branch
assert git(F, "rev-list", "--count", f"{base}..{branch}").strip() == "1"
status = dict(reversed(l.split("\t", 1)) for l in
              git(F, "diff-tree", "-r", "-M100%", "--name-status", base, branch).splitlines())
moves = [(o["sources"][0], o["targets"][0]) for o in doc["changes"] if o["op"] == "git-mv"]
assert moves, doc["changes"]
for old, new in moves:
    assert status.get(f"{old}\t{new}") == "R100", (old, new, status)
assert git(F, "rev-parse", "HEAD").strip() == base
assert not (D / ".agents/state/adopt/worktrees" / digest).exists() and not REGISTRY.exists()
# 4. on the unmerged branch, registration refuses
git(F, "checkout", "--quiet", branch)
refusal(run("adopt-project", "verify", "--repo-root", str(F), "--register", code=2), "not_integrated")
assert not REGISTRY.exists()
# 5. after the merge: verify reports and writes nothing; --register writes one row
git(F, "checkout", "--quiet", "main"); git(F, "merge", "--ff-only", "--quiet", branch)
report = json.loads(run("adopt-project", "verify", "--repo-root", str(F)))
assert (report["result"], report["registered"]) == ("adopted", False) and not REGISTRY.exists(), report
report = json.loads(run("adopt-project", "verify", "--repo-root", str(F), "--register"))
assert (report["result"], report["registered"]) == ("adopted", True), report
assert json.loads(REGISTRY.read_text()) == {"schema_version": 1, "projects": [
    {"project_id": "fixture/target", "root": str(F)}]}
# 6. fleet preflight lists the row as compatible, against the built manifest
fleet = json.loads(run("resolve-project", "platform-status", "--repo-root", str(F), "--fleet"))
rows = [r for r in fleet["fleet"] if r["project_id"] == "fixture/target"]
assert len(rows) == 1 and rows[0]["compatible"] is True and rows[0]["root"] == str(F), fleet["fleet"]
installed = os.path.realpath(H / ".agents/share/platform-manifest.json")
assert installed.startswith("/nix/store/") and fleet["platform"]["manifest_path"] == installed, fleet["platform"]
# 7-8. the conformance engine on the adopted fixture and on the branch head
def conformance(purpose, root, name):
    path = D / name
    path.write_text(run("conformance", "run", "--purpose", purpose, "--repo-root", str(root), "--offline"))
    run("conformance", "validate-report", "--input", str(path))
    return json.loads(path.read_text())
adoption = conformance("adoption", F, "adoption.json")
assert adoption["outcome"]["status"] == "passed", adoption["outcome"]
doctor = conformance("doctor", WT, "doctor.json")
bad = [c["id"] for c in doctor["checks"] if c["status"] == "failed"
       and c["domain"] in ("repository", "compatibility", "verification")]
assert not bad, bad
# 9. the operator's registry and adoption state are untouched
assert operator_state() == BEFORE, "operator state changed"
print("demo ok", new_id, branch, len(moves), "moves")
EOF
WT=$(git rev-parse --show-toplevel) H="$H" D="$D" python3 "$DRV"
rm -rf "$D"
```

Expected: the build succeeds, then one line
`demo ok sha256:<64 hex> adopt-<12 hex> 4 moves`. The plan id differs on every
run, because the fixture's commits carry fresh timestamps. On the base, before
Step 2, the driver fails at once, because neither the fixture builders it
imports nor the built `adopt-project` exist. On any failure, the assertion names the step. Keep `$D` for
the report, and see "If a gate fails". The `doctor` report's `host` checks and
its `incomplete` outcome describe the scratch machine, and they are not asserted
(D5). The build writes the git-ignored `./result`. Never run `just switch` (D8).

- [ ] **Step 8: No commit to write**

The picks and the Step 3a docstring commit are the commits, plus a D3 fix
commit only if a gate forced one.
Leave the tree clean (`git status --porcelain` is empty). Report the nine new
SHAs with their sources, the counts from Steps 5–6, and the `demo ok` line. The
package-feasibility check is sdd's cumulative delivery gate, which runs after
this task. Do not run `review-package` yourself.
