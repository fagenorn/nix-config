# Task 3: File follow-ups, verify, post the record, acceptance evidence

Spec § Solution steps 6–7, § The record (part 5 and follow-ups), § The demo comment; per D5, D7, D8 and D10. You file one issue per `filed` row, finish the record with `## Verification`, post the one demo comment on https://github.com/fagenorn/nix-config/issues/259, and write the acceptance record with AC1–AC3 measured. You change no product file.

**Files:**
- Modify: `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md` (`R`): `issue pending` tokens, and a new last section `## Verification`
- Create: `.agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.acceptance.md` (`A`)
- Tracker: one new issue per `filed` row; one comment on issue 259

**Interfaces:**
- Consumes: `R` after Task 2: no `fix pending`; `filed` rows read `issue pending (bar <k>)`; `fixed` rows read `` `<fix 8 hex>`; `<test file>::<Class>.<test name>`; failing first: `AssertionError…` `` with an optional `; mutant: …`.
- Produces: `R` final; the comment URL `https://github.com/fagenorn/nix-config/issues/259#issuecomment-<id>`; `A` with rows `AC1`–`AC4`, the evidence columns of `AC1`–`AC3` filled and every `Verdict` `—` (the sdd controller writes verdicts, per D10).

**Invariants:**
- After this task `R` holds no `fix pending` and no `issue pending`; every `filed` and `tracked` URL names an open issue; `R`'s `## ` sections are Reviewer, Coverage, Findings, Verification.
- The comment is exactly: the line `Correctness review record — CORE (PR 246), scope full: 25 of 25 product files`, a blank line, `R`'s lines from `## Reviewer` up to but not including `## Verification` at `RECORD_COMMIT`, then the record line (Step 5) (per D8).
- This task commits only `R` and `A`; its tracker writes are the follow-up issues and the one comment.
- A refused `gh` write is never retried under another identity or routed around.

- [ ] **Step 1: Preconditions**

```bash
BASE=$(git rev-parse HEAD)
R=.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md
A=.agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.acceptance.md
if grep -q 'fix pending' "$R"; then echo "fix pending remains"; exit 1; fi
test ! -e "$A"
```

Expected: exit 0. Otherwise report BLOCKED naming the failing line.

- [ ] **Step 2: File the follow-ups (per D5, D7)**

For each row whose Evidence starts `issue pending`, in table order, write `$S/issue-<ID>.md` from this to-issues template, every `<…>` filled from the row and the code at `REVIEW_SHA` so a reader without the review can follow it:

````markdown
## Parent

https://github.com/fagenorn/nix-config/issues/259: its full-scope CORE correctness review found this as <IDs>, recorded in `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md`.

## Problem

<The defect and its failure scenario at `<path>:<line>`, who meets it and why it matters, in two to four sentences.>

## What to build

<The behaviour once fixed, end to end, no code.> This is CORE scope (https://github.com/fagenorn/nix-config/issues/233, delivered by https://github.com/fagenorn/nix-config/pull/246).

**Demo:** <one line: the command or test that shows the fixed behaviour>.

## Decisions

- Not fixed in https://github.com/fagenorn/nix-config/issues/259 because <fix-here bar item k in words>.

## Acceptance criteria

- [ ] [code] <the failure scenario now behaves as the contract requires> — measured: a regression test at the module's existing test seam that fails before the fix.
- [ ] [code] The workflow test suite and the managed build pass — measured: `just agent-workflow-tests` and `just build`.

## Blocked by

None - can start immediately.
````

Then `gh issue create --repo fagenorn/nix-config --title "CORE: <the outcome to reach, plain words, at most 80 characters, no double quote, dollar sign, backtick or backslash>" --body-file "$S/issue-<ID>.md" --label agent:ready`, and replace the row's `issue pending` with the URL it prints, keeping ` (bar <k>)`. A refused create: report BLOCKED `filing refused: <first stderr line>`.

- [ ] **Step 3: Verify at the code head (per D10)**

`CODE_HEAD=$(git rev-parse HEAD)`. Run each and keep the line that shows its result:

1. The findings check (timeout 600 s):

```bash
python3 -I - "$R" <<'EOF'
import re, subprocess, sys
record = sys.argv[1]
M = "93e6059a6fece769a621657c5889278b9cb9e0d7"
def run(*a):
    return subprocess.run(list(a), check=True, capture_output=True, text=True).stdout
expected = [p for p in run("git", "diff", "--name-only", M + "^1", M).splitlines() if not p.startswith(".agents/artifacts/")]
text = open(record, encoding="utf-8").read()
lines = text.splitlines()
def section(name):
    s = lines.index(name) + 1
    e = next((i for i in range(s, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [l for l in lines[s:e] if l.strip()]
def cells(l):
    return [c.strip() for c in re.split(r"(?<!\\)\|", l.strip())[1:-1]]
cov = [cells(l) for l in section("## Coverage")[2:]]
assert [r[1].strip("`") for r in cov] == expected and all(r[4] == "whole" for r in cov), "coverage"
found = section("## Findings")
rows = [] if found == ["None."] else [cells(l) for l in found[2:]]
FIX = re.compile(r"`[0-9a-f]{8}`; `[^`]+::[A-Za-z_][A-Za-z0-9_]*\.test_[A-Za-z0-9_]+`; failing first: `AssertionError[^`]*`(; mutant: .+)?")
URL = re.compile(r"https://github\.com/fagenorn/nix-config/issues/([0-9]+)")
count, bad = {"fixed": 0, "filed": 0, "tracked": 0, "rejected": 0}, []
for ids, sev, loc, defect, disp, ev in rows:
    if sev == "Minor":
        continue
    if disp not in count:
        bad.append(ids)
        continue
    count[disp] += 1
    if disp == "fixed" and not FIX.fullmatch(ev):
        bad.append(ids)
    if disp in ("filed", "tracked"):
        m = URL.match(ev)
        tail = ev[m.end():] if m else None
        ok = m and (tail == "" if disp == "tracked" else re.fullmatch(r" \(bar [1-6]\)", tail))
        if not ok or run("gh", "issue", "view", m.group(1), "--repo", "fagenorn/nix-config", "--json", "state", "--jq", ".state").strip() != "OPEN":
            bad.append(ids)
pending = "fix pending" in text or "issue pending" in text
print(f"Critical/Important rows: {sum(count.values())} — fixed {count['fixed']}, filed {count['filed']}, tracked {count['tracked']}, rejected {count['rejected']}; violations: {', '.join(bad) or 'none'}; pending tokens: {pending}")
sys.exit(1 if bad or pending else 0)
EOF
```

2. Each `fixed` row, red at its parent with the test overlaid (timeout 900 s; skip on the weak-test route, whose mutant evidence stands from Task 2):

```bash
git worktree add --detach "$S/red-<ID>" "<fix>^"
git show "<fix>:<test file>" > "$S/red-<ID>/<test file>"
(cd "$S/red-<ID>" && launch-scope exec … -- bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest -v "$1" -k "$2"' _ <test file> <test name>) > "$S/red-<ID>.log" 2>&1; echo "exit=$?"
grep -E '^(FAIL|ERROR):|^(FAILED|OK)' "$S/red-<ID>.log"
```

For a `tests/test_agent_tools_launchers.py` test, plain `unittest` skips the whole class without `AGENT_SKILLS_INSTALLED_HOME`, so replay it as Task 2 Step 4 does: in `$S/red-<ID>` run `launch-scope exec … -- bash -c 'just agent-installed-skill-tests 2>&1' > "$S/red-<ID>.log"` (timeout 3600 s), which builds that tree and supplies the installed home, and at `CODE_HEAD` the same recipe from the worktree root (timeout 3600 s). On either route a log in which the named test is reported skipped (`skipped` on its line, or an `OK (skipped=` summary with the test absent from the `FAIL:` lines on the red run) fails the replay.

Expected: `exit=1`, one `FAIL:` line naming the test, no `ERROR:` line. Then the same test at `CODE_HEAD` from the worktree root: `exit=0`, `OK`, the test run and not skipped.

3. Each `rejected` row citing a CR test: that test at `CODE_HEAD` → `OK`.

Any unexpected result: report BLOCKED with the command and its output. Then append to `R`:

````markdown
## Verification

Run at `<CODE_HEAD 8 hex>`; the product tree is unchanged after it.

- `<command, one line>` → `<the line it printed that shows the result>`
````

one bullet per run above, the findings check first.

- [ ] **Step 4: Commit the finished record**

```bash
git add .agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md
launch-commit … -- -m "docs(issue-259): finish the CORE correctness review record" -m "<session trailers>"
RECORD_COMMIT=$(git rev-parse HEAD)
```

- [ ] **Step 5: Post the record on issue 259 (per D8)**

```bash
{ printf '%s\n\n' 'Correctness review record — CORE (PR 246), scope full: 25 of 25 product files'
  git show "$RECORD_COMMIT:$R" | sed -n '/^## Reviewer$/,/^## Verification$/p' | sed '$d'
  printf 'Record: `%s` at https://github.com/fagenorn/nix-config/blob/%s/%s\n' "$R" "$RECORD_COMMIT" "$R"
} > "$S/comment.md"
gh issue comment 259 --repo fagenorn/nix-config --body-file "$S/comment.md"
```

Keep the URL it prints and `CID`, the digits after `issuecomment-`; then `gh api repos/fagenorn/nix-config/issues/comments/<CID> --jq .body > "$S/posted.md"`. A refused comment: AC1 and AC2 below are `comment refused: <first stderr line>`, nothing is retried, and you report DONE_WITH_CONCERNS.

- [ ] **Step 6: Measure AC1 and AC2 (per D8)**

Run (timeout 300 s):

```bash
python3 -I - "$S/posted.md" "$S/comment.md" "$RECORD_COMMIT" "$R" <<'EOF'
import re, subprocess, sys
posted, composed, commit, path = sys.argv[1:5]
M = "93e6059a6fece769a621657c5889278b9cb9e0d7"
def run(*a):
    return subprocess.run(list(a), check=True, capture_output=True, text=True).stdout
expected = [p for p in run("git", "diff", "--name-only", M + "^1", M).splitlines() if not p.startswith(".agents/artifacts/")]
body = open(posted, encoding="utf-8").read().strip().splitlines()
same = body == open(composed, encoding="utf-8").read().strip().splitlines()
record = run("git", "show", f"{commit}:{path}").splitlines()
def section(lines, name):
    s = lines.index(name) + 1
    e = next((i for i in range(s, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [l for l in lines[s:e] if l.strip()]
def cells(l):
    return [c.strip() for c in re.split(r"(?<!\\)\|", l.strip())[1:-1]]
first = body[0] == "Correctness review record — CORE (PR 246), scope full: 25 of 25 product files"
rows = [cells(l) for l in section(body, "## Coverage")[2:]]
got = [r[1].strip("`") for r in rows]
missing, extra = sorted(set(expected) - set(got)), sorted(set(got) - set(expected))
whole = len(rows) == 25 and all(r[4] == "whole" for r in rows)
ac1 = first and same and not missing and not extra and whole
print(f"AC1: first line {'matches' if first else 'differs'}; body equals composed: {same}; missing {missing or 'none'}; extra {extra or 'none'}; {len(rows)} rows, all whole: {whole} (threshold empty difference, 25 whole: {'met' if ac1 else 'missed'})")
rev = section(body, "## Reviewer")
need = ("- Agent type: `reviewer`", "- Model: `", "- Sessions: B1 `",
        "- Independence: PR 246's 14 non-merge commits carry the Co-Authored-By trailers Codex ×13 and Claude Opus 5.5 ×1")
present = all(any(l.startswith(p) for l in rev) for p in need) and any("effort: high" in l for l in rev)
ids = len(re.findall(r"B[1-5]R? `[^`]+`", " ".join(l for l in rev if l.startswith("- Sessions: "))))
ac2 = present and ids >= 5 and rev == section(record, "## Reviewer")
print(f"AC2: Reviewer section equals the record's at {commit[:8]}: {rev == section(record, '## Reviewer')}; agent type, model, effort and independence tally present: {present}; {ids} agent IDs (threshold all present, 5 or more IDs, equal: {'met' if ac2 else 'missed'})")
sys.exit(0 if ac1 and ac2 else 1)
EOF
```

Expected: exit 0, both lines ending `met)`.

Then re-run Step 3's findings check (item 1, timeout 600 s) at `RECORD_COMMIT` with a clean tree, and keep its line as AC3's observation. AC3 is measured here, not at `CODE_HEAD`: Step 4 commits `R` after `CODE_HEAD`, and evidence freshness excludes only the acceptance record, so a `CODE_HEAD` measurement would read as stale. `git diff --name-only "$CODE_HEAD" "$RECORD_COMMIT"` must print only `R`'s path, so Step 3's red/green results still describe `RECORD_COMMIT`'s product tree.

- [ ] **Step 7: Write the acceptance record (per D10)**

Create `A` holding, in order: `# Acceptance record — issue 259`; a blank line; `Each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/259).`; a blank line; the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`, its `|---|…|` line, and rows `AC1`–`AC4`:

- `Criterion`: the issue's criterion line verbatim without its `- [ ] ` (`gh issue view 259 --repo fagenorn/nix-config --json body --jq .body`), each `|` written `\|`. `Kind` and `Check or command`: copied from the plan root's Acceptance map.
- `AC1`, `AC2`: `Observed` the Step 6 line and the comment URL; `Commit` `RECORD_COMMIT`'s 8 hex; `Conditions` the Step 6 command as run, the `date -u` instant, `gh` against `fagenorn/nix-config`.
- `AC3`: `Observed` the Step 6 findings-check line taken at `RECORD_COMMIT`, the Step 3 red and green results of each fixed row, and `threshold 0 violating rows: met|missed`; `Commit` `RECORD_COMMIT`'s 8 hex; `Conditions` the Step 6 findings-check command, the Step 3 replay commands, the `CODE_HEAD..RECORD_COMMIT` diff showing only `R`, and the instant.
- `AC4`: `Observed` `in final verification`; `Commit` and `Conditions` `—`.
- Every `Verdict`: `—`.

```bash
git add .agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record, AC1-AC3 evidence (issue 259)" -m "<session trailers>"
```

- [ ] **Step 8: Verify**

```bash
set -e
if grep -Eq 'fix pending|issue pending' "$R"; then exit 1; fi
test "$(grep '^## ' "$R" | tr '\n' ',')" = "## Reviewer,## Coverage,## Findings,## Verification,"
test "$(grep -c '^| AC[1-4] |' "$A")" = 4
test "$(gh api repos/fagenorn/nix-config/issues/comments/<CID> --jq .body | head -1)" = 'Correctness review record — CORE (PR 246), scope full: 25 of 25 product files'
git diff --name-only "$BASE" HEAD
```

Expected: exit 0 and the last command prints exactly `R`'s and `A`'s paths; on the refused-comment route, leave out the `gh api` line. Before this task the first `test` fails, because `R` has no `## Verification`.
