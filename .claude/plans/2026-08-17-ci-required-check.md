# CI-Gated Merge (Required `Nix Eval` Check) Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Issue: https://github.com/fagenorn/nix-config/issues/29
Spec: `.claude/specs/2026-08-17-ci-required-check-design.md` — its `## Decision ledger`
(D1–D19) is the source of truth. This plan cites rows by ID and never restates them.

**Goal:** A pull request against `main` cannot merge until a CI job that actually evaluates
the Nix configuration reports green, and that gate is version-controlled, agent-runnable,
reversible with one command, and pinned offline against the rename that would brick `main`.

**Architecture:** Three product surfaces change and no Nix code does. `.github/workflows/`
gains one honestly-named `ci.yaml` (a `git mv` of `flake-checker.yaml`) carrying two jobs —
the existing advisory `Flake Checker` and the new `Nix Eval`, which evaluates
`nixosConfigurations.anis-desktop` to a derivation path on Linux (per D3/D4/D5/D6).
`.github/branch-protection.json` holds the whole classic-protection `PUT` body (per D7–D10)
and three `justfile` recipes apply, inspect, and remove it (per D13). A stdlib
`tests/test_branch_protection.py` (per D12/D16) pins the required context to the job name,
because those two strings live in files GitHub will never reconcile for us. Enabling the
protection itself is a **post-merge rollout step**, not part of plan execution (per D11/D17).

**Tech stack:** GitHub Actions YAML, GitHub REST classic branch protection via `gh api`,
`just` 1.43, Python 3 stdlib `unittest` (`json`, `re`, `pathlib`), Markdown. No new
dependency, no `.nix` change, no new flake input.

## Global Constraints

- **Exactly four product paths change** across Tasks 1–4:
  `.github/workflows/ci.yaml` (renamed from `.github/workflows/flake-checker.yaml`),
  `.github/branch-protection.json` (create), `justfile` (modify),
  `tests/test_branch_protection.py` (create), plus `CLAUDE.md` (modify). No `.nix` file is
  touched. No file under `home/` is touched.
- **`Nix Eval` is a byte-exact contract string.** It appears in exactly two places:
  `name: Nix Eval` in `ci.yaml` and `"Nix Eval"` in `.github/branch-protection.json`. Any
  task that edits either must leave `python3 -m unittest tests/test_branch_protection.py`
  green. Per D2 there is exactly one required context; do not add a second.
- **The job backing the required context stays a plain job** (per D16): no `strategy:`, no
  `uses:` at job level, no reusable workflow. Both silently rename the check run.
- **`Nix Eval`'s runtime behaviour is unverified** — no Nix evaluation of a NixOS host is
  possible on this darwin host, and the first real CI run is its verification. Do **not**
  write a comment, a doc sentence, or a commit message asserting how long it takes, what it
  caches, or that it passes. State only what the files say.
- **Phase 6 never touches the live repository.** No `gh api --method PUT|DELETE`, no
  `just protect-main`, no `just unprotect-main`, no `git push`, no `gh pr` command. Task 5 is
  the rollout and it runs after this branch's PR has merged. An implementer that runs
  `just protect-main` during Phase 6 blocks every open PR in the live orchestration run.
- **Never disable commit signing.** No `-c commit.gpgsign=false`, no `--no-gpg-sign`. Surface
  a signing failure rather than working around it.
- **Commit trailers**, on every commit:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_011BW621YtNATjTJfsJSJXnB`
- **Never run `just switch`**, `just build`, or any activation. Nothing here enters a
  home-manager generation, so `just build` is not a gate for this plan (per D18).
- **Payload discipline.** Summarise test output to failing lines plus the final `Ran N tests`
  line; never paste a whole run into a report.

## Test seams

Existing seams only. A task that wants a new one has found a plan bug.

1. **`just agent-workflow-tests`** — the repo's only deterministic test entry point
   (`python3 -m unittest -v` over seven suites, run from the worktree root). Baseline verified
   at this branch's tip `124c84d`: **164 tests, OK**. This plan adds one suite of five tests →
   **169** at the end. Accepted friction, per D12: the recipe is named for agent workflows and
   this is CI config, and renaming it would touch every plan and skill that cites it.
2. **Offline file-shape gates** — `python3 -m json.tool`, `ruby -ryaml -e 'YAML.load_file(…)'`
   (an independent YAML parser; **PyYAML is not installed on this host**, verified, which is
   exactly why D12's test extracts job names by indentation rather than parsing), and
   `just --dry-run <recipe>` (prints a recipe's expanded commands to stderr without executing
   them). All runnable on darwin now.
3. **The live GitHub API, at ship time only** — `gh pr checks`, `gh pr view --json
   mergeStateStatus`, `gh pr merge`, `gh api .../branches/main/protection`. This is the only
   seam that observes the actual gate. It needs a real PR against the real repo and it belongs
   to Task 5, not to Phase 6. Its output is recorded as evidence, not automated.

Deliberately **not** a seam: `just build` (nothing here reaches a Nix derivation) and
`flake-checker-action`'s own output (it cannot fail by design — D1).

## Task index

| Task | Title | Files touched | Risk lane |
|------|-------|---------------|-----------|
| 1 | Rename the workflow to `ci.yaml` and add the `Nix Eval` job | `.github/workflows/flake-checker.yaml` → `.github/workflows/ci.yaml` (git mv + modify) | **full** |
| 2 | Commit the branch-protection payload and its three `just` recipes | `.github/branch-protection.json` (create), `justfile` (modify) | **full** |
| 3 | Pin the required context to the job name offline | `tests/test_branch_protection.py` (create), `justfile` (modify) | **full** |
| 4 | Correct `CLAUDE.md` and sweep every offline gate | `CLAUDE.md` (modify) | **low-risk** |
| 5 | **ROLLOUT — ship-time only, NOT Phase 6** | no repo files; live repo settings + sibling PRs | **full** |

**Lane rationale.** Tasks 1, 2 and 3 are **full** and none of them is mechanical, whatever the
line counts suggest. Task 1 defines the merge gate for every future change to this repository
— a release-adjacent public contract — and the `git mv` is not a rename with no semantic
effect, because the file's triggers and job set change with it. Task 2 is a payload that, once
applied, can refuse pushes to `main` from every actor including the owner (D8); it is a
security- and release-surface change. Task 3 is the only offline defence against the
bricked-`main` failure, and its own characteristic bug is a vacuously-passing test (a regex
that matches nothing still goes green) — precisely what a full review must catch. Task 4 is
**low-risk**: one sentence of documentation whose content is fixed verbatim in the spec (D14),
bounded and locally verifiable, changing no behaviour. Task 5 is **full** and is not code: it
mutates live repository settings and other agents' open pull requests.

## Decisions

The spec's ledger is authoritative. This plan rests on D1–D16 and adds D17–D19 (appended to
the spec in this plan's commit):

- **D17** — the rollout runbook lives here as Task 5 rather than in a new doc file.
- **D18** — Phase-6 verification is offline-only; the exact `nix eval` invocation and the
  PR-only `cancel-in-progress` are fixed here.
- **D19** — `tests/` at the repo root is the home for the new suite, next to
  `test_agent_costs.py`.

---

## Task 1: Rename the workflow to `ci.yaml` and add the `Nix Eval` job

**Files:**
- Rename + modify: `.github/workflows/flake-checker.yaml` → `.github/workflows/ci.yaml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the literal job name `Nix Eval` (a four-space-indented `    name: Nix Eval` line
  under a two-space-indented job key `  nix-eval:`) and the job name `Flake Checker` (under
  `  flake-checker:`). Task 2 writes `"Nix Eval"` into the protection payload; Task 3 asserts
  the two agree and depends on this exact indentation convention.

**Invariants:**
- The file has exactly one top-level `jobs:` mapping with exactly two job keys, each carrying
  a `name:` at four spaces of indentation. Workflow name at column 0, step names at six or
  more. Task 3's extractor reads this convention literally.
- Neither job declares `strategy:` or `uses:` at four-space (job-level) indentation — per D16
  a matrix suffixes the check-run name and a reusable workflow prefixes it, either of which
  decouples the reported name from the required context with no error anywhere.
- `pull_request` carries **no** `types:` key, so GitHub's default set applies. `reopened` is
  in that default set and Task 5's sibling-unblock procedure depends on it.
- The rename is a `git mv` so history follows the file.

- [ ] **Step 1: Rename the file and confirm git records a rename**

```bash
git mv .github/workflows/flake-checker.yaml .github/workflows/ci.yaml
git status --porcelain
```

Expected: a single `R  .github/workflows/flake-checker.yaml -> .github/workflows/ci.yaml`
line. If it prints `D` plus `A`, the rename was not staged as one — redo it with `git mv`.

- [ ] **Step 2: Write the new workflow**

Replace the whole content of `.github/workflows/ci.yaml` with exactly this. The `Flake
Checker` job keeps its existing steps minus `DeterminateSystems/magic-nix-cache-action@v2`
(retired upstream — per D6, no replacement cache is added).

```yaml
# Adapted from https://github.com/wimpysworld/nix-config/blob/main/.github/workflows/flake-checker.yml
name: CI

on:
  pull_request:
    branches:
      - main
  push:
    branches:
      - main
  schedule:
    # l33t o'clock
    - cron: '37 13 * * *'
  workflow_dispatch:

# One run per pull request; a new push to a PR supersedes that PR's in-flight run.
# Runs on `main` and on the cron are keyed by ref and are never cancelled, so every
# commit that lands on `main` keeps its own reported result.
concurrency:
  group: ci-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  flake-checker:
    name: Flake Checker
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0
      - uses: DeterminateSystems/nix-installer-action@v4
      - uses: DeterminateSystems/flake-checker-action@v5

  # `Nix Eval` is the required status check on `main`; the same string is the sole
  # entry in .github/branch-protection.json. Renaming this job — or giving it a
  # `strategy:` or a `uses:`, which make GitHub report it under a different name —
  # leaves that required context unreportable and blocks every merge to `main` with
  # no error pointing at the cause. tests/test_branch_protection.py pins both files
  # together; run `just agent-workflow-tests` after editing either.
  nix-eval:
    name: Nix Eval
    # The daily cron is flake-checker's; flake.lock is pinned, so a scheduled
    # re-evaluation of an unchanged tree cannot report anything new.
    if: github.event_name != 'schedule'
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0
      - uses: DeterminateSystems/nix-installer-action@v4
      - name: Evaluate nixosConfigurations.anis-desktop
        run: |
          nix eval --show-trace \
            --extra-experimental-features 'nix-command flakes' \
            --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath'
```

Per D3 this evaluates only the NixOS host: it forces `lib/`, `home/default.nix`,
`home/common/**` and `hosts/common/**` through the evaluator, while `nix flake check` would
also reach `darwinConfigurations.mbp`, which has no aarch64-darwin builder here. Evaluation
reaches import-from-derivation, so the runner must be a native `x86_64-linux` *builder* — the
reason for `ubuntu-24.04` rather than a bare evaluator (per D18, `--show-trace` is on so the
first failure is diagnosable from the log alone).

- [ ] **Step 3: Verify — the file parses, and every invariant above is observable**

```bash
ruby -ryaml -e 'd=YAML.load_file(".github/workflows/ci.yaml"); \
  raise "name" unless d["name"]=="CI"; \
  raise "jobs" unless d["jobs"].keys.sort==["flake-checker","nix-eval"]; \
  raise "ctx"  unless d["jobs"]["nix-eval"]["name"]=="Nix Eval"; \
  raise "adv"  unless d["jobs"]["flake-checker"]["name"]=="Flake Checker"; \
  raise "pr"   unless d[true]["pull_request"]["branches"]==["main"]; \
  raise "types" if d[true]["pull_request"].key?("types"); \
  raise "plain" if d["jobs"]["nix-eval"].key?("strategy") || d["jobs"]["nix-eval"].key?("uses"); \
  puts "ci.yaml OK"'
grep -c 'magic-nix-cache' .github/workflows/ci.yaml
grep -n '^    name:' .github/workflows/ci.yaml
```

Expected: `ci.yaml OK`; `grep -c` prints `0` (exit 1 — that is the expected exit for zero
matches, not a failure); the last `grep` prints exactly two lines,
`    name: Flake Checker` and `    name: Nix Eval`.

Note `d[true]` is not a typo — YAML 1.1 parses the bare key `on:` as the boolean `true`.

**This gate could fail at the base commit and must:** at `124c84d`, `.github/workflows/ci.yaml`
does not exist and `grep -c magic-nix-cache .github/workflows/flake-checker.yaml` prints `1`.
Confirm that before starting, so "already done" is not a possible reading.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/
git commit -m "ci(issue-29): rename the workflow to ci.yaml and add the Nix Eval job

Nix Eval evaluates nixosConfigurations.anis-desktop to a derivation path on
ubuntu-24.04 and runs on pull requests; Flake Checker keeps its advisory role.
Drops the retired magic-nix-cache-action.

Refs https://github.com/fagenorn/nix-config/issues/29"
```

---

## Task 2: Commit the branch-protection payload and its three `just` recipes

**Files:**
- Create: `.github/branch-protection.json`
- Modify: `justfile`

**Interfaces:**
- Consumes: the job name `Nix Eval` produced by Task 1.
- Produces: `.github/branch-protection.json` with the shape
  `{"required_status_checks": {"strict": bool, "contexts": [str]}, "enforce_admins": bool,
  "required_pull_request_reviews": null, "restrictions": null}`, and three `just` recipes —
  `protect-main`, `unprotect-main`, `show-protection`. Task 3 reads the JSON file; Task 4
  names all three recipes in `CLAUDE.md`; Task 5 runs them.

**Invariants:**
- All four top-level keys are present, two of them explicitly `null` (per D10) — the API
  returns 422 for a body missing either.
- `enforce_admins` is `true` (per D8) and `strict` is `false` (per D9).
- `contexts` is exactly `["Nix Eval"]` — one required context, per D2.
- Recipes use `{owner}`/`{repo}` placeholders and write `main` **literally**; `{branch}` is
  never used, because `gh` expands it to the *current* branch and a recipe run from a feature
  worktree would then protect the wrong branch (per D13).
- `protect-main` is safely re-runnable: `PUT` replaces the entire protection object, so a
  second run converges rather than accumulating.
- No `[macos]`/`[linux]` attribute on any of the three — `gh` is available on both platforms
  and the recipes are platform-independent.

- [ ] **Step 1: Write the payload**

`.github/branch-protection.json`, byte for byte (JSON permits no comments; the rationale for
every field is D7–D10):

```json
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["Nix Eval"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
```

- [ ] **Step 2: Add the three recipes to the `justfile`**

Append a new section immediately **after** the `agent-model-matrix` recipe and **before** the
`## remote nix vm installation` section, matching the file's existing `## <section>` +
`# <description>` comment style:

```just
## branch protection
# Apply the committed protection payload to `main`. Idempotent: the API replaces the
# whole protection object, so re-running after a job rename converges. `main` is
# written literally on purpose — gh's {branch} placeholder expands to the *current*
# branch, which would point this at whatever branch you are standing on.
protect-main:
  gh api --method PUT repos/{owner}/{repo}/branches/main/protection \
    --input .github/branch-protection.json

# Remove branch protection from `main`. This is the documented undo for protect-main
# and the escape hatch if the required context is ever wrong.
unprotect-main:
  gh api --method DELETE repos/{owner}/{repo}/branches/main/protection

# Show the protection actually applied to `main`. Note the API asymmetry: PUT takes
# enforce_admins as a plain boolean, GET returns it as an object, {"enabled": true}.
show-protection:
  gh api repos/{owner}/{repo}/branches/main/protection
```

- [ ] **Step 3: Verify — the payload parses to the right shape and the recipes expand
      correctly, without touching the live repository**

```bash
python3 -m json.tool .github/branch-protection.json > /dev/null && echo "json OK"
python3 -c "
import json
p = json.load(open('.github/branch-protection.json'))
assert set(p) == {'required_status_checks','enforce_admins','required_pull_request_reviews','restrictions'}, sorted(p)
assert p['enforce_admins'] is True
assert p['required_status_checks'] == {'strict': False, 'contexts': ['Nix Eval']}
assert p['required_pull_request_reviews'] is None and p['restrictions'] is None
print('payload OK')
"
just --list | grep -E 'protect-main|unprotect-main|show-protection'
just --dry-run protect-main
just --dry-run unprotect-main
just --dry-run show-protection
grep -c '{branch}' justfile
```

Expected: `json OK`; `payload OK`; three recipes listed; each `--dry-run` prints its `gh api
…` line to stderr and **executes nothing** (`--dry-run` is `just`'s no-op mode — confirm no
`gh` network output appears); `grep -c` prints `0` (exit 1 is the expected exit for zero
matches).

**This gate could fail at the base commit and must:** at `124c84d`,
`.github/branch-protection.json` does not exist and `just --list` has no `protect-main`.

- [ ] **Step 4: Commit**

```bash
git add .github/branch-protection.json justfile
git commit -m "ci(issue-29): commit the branch-protection payload and its just recipes

protect-main / unprotect-main / show-protection apply, remove and inspect classic
protection on main from .github/branch-protection.json. Not applied here — the
rollout is a post-merge step.

Refs https://github.com/fagenorn/nix-config/issues/29"
```

---

## Task 3: Pin the required context to the job name offline

**Files:**
- Create: `tests/test_branch_protection.py`
- Modify: `justfile` (add the new suite to `agent-workflow-tests`)
- Reads: `.github/workflows/ci.yaml` (Task 1), `.github/branch-protection.json` (Task 2)

**Interfaces:**
- Consumes: `Nix Eval` as a four-space-indented `name:` in `ci.yaml`, and
  `required_status_checks.contexts` in the payload.
- Produces: five `unittest` tests, wired into `just agent-workflow-tests`. Task 4's sweep
  expects the recipe to report **169 tests, OK** (baseline at `124c84d` is 164).

**Invariants:**
- The test asserts only what a `unittest` over YAML text and JSON can observe: that the two
  files agree. It never asserts that `Nix Eval` passes or that GitHub honours the protection.
- **No vacuous pass.** Every list the tests iterate is asserted non-empty first. A regex that
  stops matching must turn the suite red, not green — this is the whole point of the file.
- No third-party import. PyYAML is **not installed on this host** (verified), so job names are
  extracted by indentation depth, per D12.
- Paths resolve from `__file__`, so the suite passes from any cwd.

- [ ] **Step 1: Write the failing test**

Create `tests/test_branch_protection.py` with exactly this content:

```python
"""Pin the CI required-status-check contract.

The context required by branch protection and the job name GitHub reports are the
same string held in two files that GitHub will never reconcile for us. A rename on
either side raises no error anywhere: it leaves `main` waiting forever on a context
that never reports, with nothing in the UI pointing at the cause. These tests are
the only offline place that failure can surface.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yaml"
PROTECTION = REPO_ROOT / ".github" / "branch-protection.json"

# ci.yaml's indentation convention: workflow name at column 0, job keys at two
# spaces, job attributes at four, step attributes at six or more. PyYAML is not a
# guaranteed dependency on this host, so the convention is the parser.
JOB_KEY_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
JOB_NAME_RE = re.compile(r"^    name:\s*(\S.*?)\s*$")
RENAMING_KEY_RE = re.compile(r"^    (strategy|uses):")
TOP_LEVEL_KEY_RE = re.compile(r"^[A-Za-z]")

REQUIRED_PAYLOAD_KEYS = {
    "required_status_checks",
    "enforce_admins",
    "required_pull_request_reviews",
    "restrictions",
}


def workflow_lines():
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def _top_level_block(key):
    """Lines under a column-0 `key:`, up to the next column-0 key."""
    lines = workflow_lines()
    header = f"{key}:"
    if header not in lines:
        raise AssertionError(f"{WORKFLOW} has no top-level `{header}`")
    out = []
    for line in lines[lines.index(header) + 1:]:
        if TOP_LEVEL_KEY_RE.match(line):
            break
        out.append(line)
    return out


def job_blocks():
    """Map each job key in `jobs:` to the lines of its block."""
    blocks = {}
    current = None
    for line in _top_level_block("jobs"):
        match = JOB_KEY_RE.match(line)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def job_names():
    """Map each job's reported check-run name to its job key."""
    names = {}
    for key, block in job_blocks().items():
        for line in block:
            match = JOB_NAME_RE.match(line)
            if match:
                names[match.group(1)] = key
                break
    return names


def trigger_block(name):
    """Lines under `  <name>:` inside the `on:` block, or None if absent."""
    block = _top_level_block("on")
    header = f"  {name}:"
    if header not in block:
        return None
    out = []
    for line in block[block.index(header) + 1:]:
        if re.match(r"^  \S", line):
            break
        out.append(line)
    return out


def payload():
    return json.loads(PROTECTION.read_text(encoding="utf-8"))


def required_contexts():
    return payload()["required_status_checks"]["contexts"]


class WorkflowShape(unittest.TestCase):
    def test_job_names_are_extractable(self):
        """Guards every other test here: an extractor that matches nothing would
        make the context/job-name comparisons pass vacuously."""
        names = job_names()
        self.assertTrue(
            names,
            f"no four-space `name:` job names found in {WORKFLOW}; the file's "
            f"indentation convention changed and every other assertion in this "
            f"suite is now vacuous",
        )
        self.assertIn("Nix Eval", names)
        self.assertIn("Flake Checker", names)

    def test_pull_request_on_main_is_a_trigger(self):
        """Without this trigger a PR head carries zero check runs and the required
        context can never report."""
        block = trigger_block("pull_request")
        self.assertIsNotNone(block, f"{WORKFLOW} has no `pull_request:` trigger")
        self.assertIn("- main", [line.strip() for line in block])


class RequiredContexts(unittest.TestCase):
    def test_every_required_context_is_a_job_name(self):
        contexts = required_contexts()
        self.assertTrue(contexts, "branch protection requires at least one context")
        names = job_names()
        for context in contexts:
            self.assertIn(
                context,
                names,
                f"required context {context!r} in {PROTECTION.name} matches no job "
                f"`name:` in {WORKFLOW.name} (found {sorted(names)}); merges to main "
                f"would block forever waiting for it",
            )

    def test_required_jobs_are_plain_jobs(self):
        """A matrix job reports as `name (value)` and a reusable workflow as
        `caller / callee`; either decouples the reported check-run name from the
        required context while a pure string comparison still passes."""
        names = job_names()
        blocks = job_blocks()
        for context in required_contexts():
            key = names[context]
            offenders = [
                line.strip() for line in blocks[key] if RENAMING_KEY_RE.match(line)
            ]
            self.assertEqual(
                [],
                offenders,
                f"job {key!r} backs required context {context!r} and must stay a "
                f"plain job; found {offenders}",
            )


class ProtectionPayload(unittest.TestCase):
    def test_payload_carries_every_key_the_api_requires(self):
        """The API rejects a body missing any of the four keys with a 422 at apply
        time — long after the hand-edit that dropped one."""
        data = payload()
        self.assertEqual(REQUIRED_PAYLOAD_KEYS, set(data))
        self.assertIs(True, data["enforce_admins"])
        self.assertIs(False, data["required_status_checks"]["strict"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail — then prove it is not vacuous**

```bash
python3 -m unittest -v tests.test_branch_protection
```

Expected at this point: **PASS, 5 tests** (Tasks 1 and 2 already landed the files it reads).
That is not yet evidence, so demonstrate each edge in turn — make the edit, see red, revert:

```bash
# a) required context renamed on one side only
python3 - <<'PY'
import pathlib; p = pathlib.Path(".github/branch-protection.json")
p.write_text(p.read_text().replace("Nix Eval", "Nix Evaluate"))
PY
python3 -m unittest tests.test_branch_protection 2>&1 | tail -3   # expect: FAILED (failures=1)
git checkout -- .github/branch-protection.json

# b) the job backing a required context becomes a matrix job
python3 - <<'PY'
import pathlib; p = pathlib.Path(".github/workflows/ci.yaml")
p.write_text(p.read_text().replace("    name: Nix Eval\n", "    name: Nix Eval\n    strategy:\n      matrix:\n        os: [ubuntu-24.04]\n"))
PY
python3 -m unittest tests.test_branch_protection 2>&1 | tail -3   # expect: FAILED (failures=1)
git checkout -- .github/workflows/ci.yaml

# c) the pull_request trigger is removed
python3 - <<'PY'
import pathlib; p = pathlib.Path(".github/workflows/ci.yaml")
p.write_text(p.read_text().replace("  pull_request:\n    branches:\n      - main\n", ""))
PY
python3 -m unittest tests.test_branch_protection 2>&1 | tail -3   # expect: FAILED (failures=1)
git checkout -- .github/workflows/ci.yaml

git status --porcelain   # expect: empty for these two paths
```

Record the three `FAILED` lines in the task report — they are AC5's evidence. If any of the
three prints `OK`, the suite is vacuous and the task is not done.

- [ ] **Step 3: Wire the suite into the repo's test entry point**

In `justfile`, add `tests/test_branch_protection.py` as the final path of the
`agent-workflow-tests` recipe's `python3 -m unittest -v` invocation, after
`tests/test_agent_costs.py`, keeping the trailing-backslash continuation style:

```just
    tests/test_agent_costs.py \
    tests/test_branch_protection.py
```

- [ ] **Step 4: Verify**

```bash
just agent-workflow-tests 2>&1 | tail -3
```

Expected: `Ran 169 tests`, `OK`. The baseline at `124c84d` is **164 tests, OK** — a run that
still reports 164 means the recipe edit did not take.

- [ ] **Step 5: Commit**

```bash
git add tests/test_branch_protection.py justfile
git commit -m "test(issue-29): pin the required context to the ci.yaml job name

Five stdlib assertions: job names are extractable at all, pull_request on main is
a trigger, every required context matches a job name, no required job is a matrix
or reusable-workflow job, and the payload carries all four API-required keys.

Refs https://github.com/fagenorn/nix-config/issues/29"
```

---

## Task 4: Correct `CLAUDE.md` and sweep every offline gate

**Files:**
- Modify: `CLAUDE.md` (the paragraph that today begins "There is **no test/lint suite**")

**Interfaces:**
- Consumes: `ci.yaml`, `.github/branch-protection.json`, and the three recipe names from
  Tasks 1–3. Every path and recipe name the new paragraph mentions must already exist.
- Produces: nothing later tasks read.

**Invariants:**
- The paragraph describes only what is in the tree at this commit. Per D14 it lands here and
  not in the design commit, precisely so it is true at `HEAD`. It makes no claim about
  runtime, timing, or caching.
- The stale first clause ("no test/lint suite") is corrected in the same edit — the repo has
  eight Python suites behind `just agent-workflow-tests` as of Task 3.
- The two honest holes stay named rather than hidden: darwin is not evaluated in CI (D3) and
  `just agent-workflow-tests` does not run in CI (D15).

- [ ] **Step 1: Replace the paragraph**

Find the paragraph in `CLAUDE.md` beginning "There is **no test/lint suite**" and ending
"— it does not build or deploy." Replace the whole paragraph with exactly this text (verbatim
from the spec's *The `CLAUDE.md` sentence* section; do not paraphrase, do not reflow):

> There is **no unit-test suite for the Nix configs** — `just build` (a successful Nix
> evaluation + build) is the local verification step. After editing any `.nix`, run
> `just build` before claiming success; switch only when asked. CI
> (`.github/workflows/ci.yaml`) runs on pull requests, on push to `main`, and daily:
> `Flake Checker` annotates `flake.lock` health without failing, and **`Nix Eval` evaluates
> `nixosConfigurations.anis-desktop` on Linux and is a required status check on `main`** —
> with `enforce_admins` on, `gh pr merge` (including `--admin`) and direct pushes to `main`
> are refused until it is green. CI does not build or deploy, does not evaluate
> `darwinConfigurations.mbp`, and does not run `just agent-workflow-tests`; the mac and the
> Python suites are still the author's local responsibility. `just protect-main` /
> `just unprotect-main` / `just show-protection` manage that protection from
> `.github/branch-protection.json`.

(Plain paragraph text, not a blockquote — the `>` markers above delimit the quotation in this
plan and are not part of the file.)

- [ ] **Step 2: Verify the doc edit and sweep every gate this plan owns**

```bash
grep -c 'flake-checker.yaml' CLAUDE.md
grep -c 'no test/lint suite' CLAUDE.md
grep -c 'ci.yaml' CLAUDE.md
grep -c 'just protect-main' CLAUDE.md
just agent-workflow-tests 2>&1 | tail -3
python3 -m json.tool .github/branch-protection.json > /dev/null && echo "json OK"
ruby -ryaml -e 'YAML.load_file(".github/workflows/ci.yaml"); puts "yaml OK"'
just --list > /dev/null && echo "justfile OK"
git diff --stat 124c84d..HEAD -- .github/ justfile tests/test_branch_protection.py CLAUDE.md
```

Expected: the first two `grep -c` print `0` (exit 1 for zero matches is expected); the next
two print `1` each; `Ran 169 tests` / `OK`; `json OK`; `yaml OK`; `justfile OK`; and the
`git diff --stat` names exactly five paths — `.github/branch-protection.json`,
`.github/workflows/ci.yaml` (with `.github/workflows/flake-checker.yaml` as its rename
source), `justfile`, `tests/test_branch_protection.py`, `CLAUDE.md`.

The pathspec is deliberate: the range also carries this plan and the spec, and a ship-time
sync merge would pull in whatever `main` advanced by. Do not grade the raw range.

**This gate could fail at the base commit and must:** at `124c84d`,
`grep -c 'flake-checker.yaml' CLAUDE.md` prints `1` and `grep -c 'ci.yaml' CLAUDE.md`
prints `0` — exactly inverted.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(issue-29): describe the CI gate and correct the stale test claim

CLAUDE.md now names ci.yaml, the required Nix Eval context and the three
protection recipes, and stops claiming the repo has no test suite. Names the two
holes: darwin is not evaluated in CI and agent-workflow-tests does not run there.

Refs https://github.com/fagenorn/nix-config/issues/29"
```

**Phase 6 ends here.** Do not proceed to Task 5 during plan execution.

---

## Task 5: ROLLOUT — ship-time only, NOT Phase 6

**This task changes no file in the repository.** It mutates live GitHub settings and other
agents' open pull requests, and every step of it happens **after this branch's PR has merged
into `main`**. An implementer running any of it during Phase 6 blocks every open PR in the
live `issues-29-33-20260817` orchestration run. The ordering is the design (per D11), not an
implementation detail.

**Owner:** whoever runs `ship-issue` for https://github.com/fagenorn/nix-config/issues/29,
after the merge completes. **Prerequisite:** `.github/workflows/ci.yaml` is on `main`.

**Invariants:**
- Protection is applied **last**, and only after every pending direct-to-`main` commit is
  pushed. `enforce_admins: true` removes the owner's bypass and required checks apply to
  direct pushes, so an unpushed commit is expected to be refused afterwards.
- Every PR open at the moment protection lands needs one new `pull_request` event before it
  can merge. GitHub never retroactively triggers workflows and a `pull_request` run cannot be
  started with `workflow_dispatch`.
- `just unprotect-main` is the undo and must be proven to work before it is needed in anger.

- [ ] **Step 1: This branch's PR merges first**

Ship normally. The PR itself is the first demonstration that check runs now appear on a PR
head: `gh pr checks <n>` should list `Nix Eval` and `Flake Checker`, where the same command
at base commit `b59ff22` prints "no checks reported" (AC1). Nothing is required yet, so the PR
merges whatever the checks say — but record their outcome, and if `Nix Eval` is red, fix it on
this branch before continuing. **Do not apply protection to make this PR gate itself**: the
context cannot report until `ci.yaml` is on `main`, so the PR would block on a check that does
not exist.

- [ ] **Step 2: Push every pending direct-to-`main` commit — unconditionally, before Step 3**

```bash
git -C /Users/anis/tmp/nix-config log --oneline origin/main..main
git -C /Users/anis/tmp/nix-config push origin main
```

Local `main` is one commit ahead of `origin/main` at planning time (`c560008`, the
out-of-scope record). If the range is empty, this step is already satisfied. Do not skip it on
the theory that protection may be laxer than expected — if it is, nothing was lost.

- [ ] **Step 3: Apply protection and read back what actually landed**

```bash
just protect-main
just show-protection
gh api repos/fagenorn/nix-config/branches/main/protection \
  --jq '[.required_status_checks.contexts, .required_status_checks.strict, .enforce_admins.enabled]'
```

Expected: `[["Nix Eval"], false, true]` (AC2). Note the API asymmetry — `enforce_admins` goes
in as a boolean and comes back as `{"enabled": true}`.

- [ ] **Step 4: Demonstrate the gate on a throwaway PR, then prove the undo**

On a scratch branch off `main`, open a PR and record:
- `gh pr view <n> --json mergeStateStatus` reporting `BLOCKED` while `Nix Eval` is pending or
  red, with `gh pr merge <n>` **and** `gh pr merge <n> --admin` both exiting non-zero (AC3).
- A commit that breaks evaluation of a shared module turning `Nix Eval` red, and its revert
  turning it green — capture both run URLs (AC4).
- `just unprotect-main` followed by `gh api repos/fagenorn/nix-config/branches/main/protection`
  returning 404 "Branch not protected" (AC6) — then `just protect-main` again and re-confirm
  Step 3's output, which also demonstrates the recipe's idempotence.

Close the throwaway PR and delete its branch.

- [ ] **Step 5: Unblock the sibling PRs**

Every PR open at Step 3 now shows `Expected — Waiting for status to be reported` and cannot
merge until `Nix Eval` reports on its head. Re-fire `pull_request` on each with zero commits
(`reopened` is in the default trigger type set, which Task 1's invariants preserve):

```bash
gh pr list --state open --json number,title
# for each open sibling PR (issues 30-33):
gh pr close <n> && gh pr reopen <n>
gh pr checks <n>
```

Siblings do **not** need `ci.yaml` on their own branch — a `pull_request` run executes the
workflow from the base/head merge commit. An empty commit on the head branch works equally
well if close/reopen is undesirable for a given PR.

- [ ] **Step 6: Record the evidence**

Capture Steps 1–5's command output as the issue's closing comment: the AC1 before/after, the
AC2 `--jq` line, the AC3 refusals, the AC4 run URLs, the AC5 three red runs from Task 3
Step 2, the AC6 404, and the AC7 `CLAUDE.md` grep. Do not claim an acceptance criterion
without its output.

---

## Follow-up (not this slice)

`just agent-workflow-tests` is not run in CI (per D15) — the largest honest hole in this gate,
since most churn in this repo is Python and Markdown under `home/common/agent-skills/**` and
`Nix Eval` passes every such change without executing one assertion. Closing it is one job in
`ci.yaml` plus one string in `.github/branch-protection.json`, and it needs `just` on the
runner. Open it as a follow-up issue after Task 5 completes.
