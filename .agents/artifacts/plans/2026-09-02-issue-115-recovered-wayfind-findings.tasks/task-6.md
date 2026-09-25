# Task 6: #80 — added seams, prototype references, the #86 correction, package sweep

**Files:**
- Modify: `.claude/specs/2026-08-20-release-lifecycle-seams-research.md`
- Test: none — this repository has no test suite for documentation. The task's
  gates are the two shell blocks in Step 2/Step 5, run from the worktree root.

**Interfaces:**

- Consumes: the spec
  `.claude/specs/2026-09-02-issue-115-recovered-wayfind-findings-design.md` —
  the **added claims** half of its
  `### .claude/specs/2026-08-20-release-lifecycle-seams-research.md (#80)`
  table (`A80.1`–`A80.4`), its `## Seam taxonomy`, its
  `**Terminology guards for #80**`, and rows D1–D3, D5, D7, D8, D10, D11, D12,
  D14, D16, D17, D22. From Task 4, in the same document package (its root, or
  an evidence member if Task 4's Step 7 moved it): the `## Seam roster` section
  holding one three-column table `| Seam | Class | Detail |` whose `Class`
  column carries exactly one of `release-unit seam`, `enforcement seam`,
  `durable-state seam` and whose `Detail` column carries the verbatim text of a
  `##`/`###` heading in the same document package — bare when the heading is in
  the root, and `<member repo-relative path> § <heading text>` when it is in an
  evidence member (per D22); its `### Field definitions`
  subsection declaring **locator**, **identity**, **evidence**, **rollback**
  and the four label lines `Locator:`, `Identity:`, `Evidence:`, `Rollback:`;
  and five filled `release-unit seam` rows.
- Produces: the completed eleven-row roster and the finished package. Nothing
  after this task consumes it.

**Invariants:**

- Task 4's five `release-unit seam` rows and their detail subsections are
  **extended, never rewritten or reordered**. This task adds six rows and their
  detail sections; the release-unit half of the roster is unchanged.
- The roster ends with exactly eleven rows: five `release-unit seam`, one
  `enforcement seam`, five `durable-state seam` (per D11).
- Each of the six added seams has its own detail section carrying all four
  label lines `Locator:`, `Identity:`, `Evidence:`, `Rollback:`, with the
  meanings Task 4's `### Field definitions` declares. `Locator:` names its root
  explicitly — caller-supplied repository root, primary checkout, feature
  worktree, `$TMPDIR`, or the tracker itself. `Identity:` says which sense of
  *identity* it uses (per D10). `Rollback:` states the reversibility limit
  where nothing undoes the record.
- **`A80.1`'s "only machine enforcement" claim is bounded** (per D14): the
  guard is the only enforcement **inside the agent's own execution path**,
  adjudicating before the action runs; live branch protection and the required
  `Nix Eval` status context on `main` are forge-side enforcement the guard
  *consults*, not enforcement it replaces. An unbounded restatement would
  contradict this repository's own CI configuration and is a defect.
- **`A80.3`'s shas are exact, full 40-character shas**, each with the `origin`
  branch that reaches it, the directory it contains, and the command a reader
  runs to retrieve it. Verify each with `git cat-file -e <sha>^{commit}` and
  `git ls-remote origin` before writing it (per D3, V4).
- **`A80.4` corrects #86 in this document only.** No tracker comment is edited,
  including #86's (per D7). The correction names #86's statement, states that it
  is false, and gives the `git ls-remote origin` evidence with the branch and
  sha.
- The `.superpowers/` name is stated to be historical: the document uses the
  literal paths and records that no Superpowers input, patch, marketplace or
  plugin exists in this repository (per D10, `CLAUDE.md`).
- The six added seams are never implied to be release units. The *state* and
  *identity* disambiguations from Task 4 apply here too and are the reason each
  added row says which sense it uses.
- Length is governed by the-bar's *Token economy*; `artifact-budget` is never
  run against any of the four documents (per D8).

- [ ] **Step 1: Write both gates first, before editing the document**

Save this to `"${TMPDIR:-/tmp}/gate-80b.sh"` — the #80 completion gate.

```bash
#!/usr/bin/env bash
set -uo pipefail
DOC=".claude/specs/2026-08-20-release-lifecycle-seams-research.md"
fail=0
say() { echo "FAIL: $*"; fail=1; }
test -f "$DOC" || { echo "FAIL: $DOC does not exist"; exit 1; }

heads=$(grep -E '^#{2,4} ' "$DOC" | sed -E 's/^#{2,4} //')
cov=$(awk '/^## Coverage of the resolution summary$/{f=1;next} /^## /{f=0} f' "$DOC")
# The roster's TABLE ROWS only. Stop at the next heading of any level, so
# `### Field definitions` — which names every class literal in its prose — is
# outside the block, and keep only pipe-delimited rows that are not the header
# or the separator. Grepping the whole section counts those prose mentions and
# silently inflates every class count.
roster=$(awk '/^## Seam roster$/{f=1;next} /^#{2,4} /{f=0} f' "$DOC" \
  | grep '^|' | grep -v '^| *Seam *|' | grep -vE '^\|[ :|-]+\|$')

# Roster class counts, read from the Class column (field 3) of those rows:
# 5 / 1 / 5 = eleven rows (D11).
for pair in "release-unit seam:5" "enforcement seam:1" "durable-state seam:5"; do
  cls="${pair%:*}"; want="${pair##*:}"
  got=$(printf '%s\n' "$roster" \
    | awk -F'|' -v c="$cls" '{gsub(/^ +| +$/,"",$3)} $3==c' | wc -l | tr -d ' ')
  [ "$got" -eq "$want" ] || say "roster has $got '$cls' rows, expected $want"
done

# One deterministic resolver for every heading reference in this package, used
# for roster Detail cells and coverage rows alike (per D22). A bare value names
# a heading in the root; a `<member repo-relative path> § <heading>` value
# splits on the FIRST ' § ' and names a heading in that member file. Either way
# the heading must match character-for-character.
resolve() {  # $1 = reference; echoes nothing on success, a reason on failure
  ref="$1"
  case "$ref" in
    *' § '*)
      f="${ref%% § *}"; h="${ref#* § }"
      [ -f "$f" ] || { echo "member '$f' does not exist"; return; }
      grep -E '^#{2,4} ' "$f" | sed -E 's/^#{2,4} //' | grep -qxF -- "$h" \
        || echo "'$h' is not a heading in $f"
      ;;
    *)
      printf '%s\n' "$heads" | grep -qxF -- "$ref" \
        || echo "'$ref' is not a heading in $DOC"
      ;;
  esac
}

# Every roster Detail column resolves.
printf '%s\n' "$roster" | while IFS= read -r row; do
  det=$(printf '%s\n' "$row" | awk -F'|' '{print $4}' | sed -E 's/^ +| +$//g')
  [ -n "$det" ] || { echo "FAIL: a roster row names no Detail section"; continue; }
  why=$(resolve "$det"); [ -z "$why" ] || echo "FAIL: roster Detail $why"
done | tee "${TMPDIR:-/tmp}/roster-detail.log"
[ ! -s "${TMPDIR:-/tmp}/roster-detail.log" ] || fail=1

# Each added seam's detail section carries the four label lines.
printf '%s\n' "$roster" \
  | awk -F'|' '{gsub(/^ +| +$/,"",$3)} $3=="enforcement seam" || $3=="durable-state seam"' \
  | while IFS= read -r row; do
  det=$(printf '%s\n' "$row" | awk -F'|' '{print $4}' | sed -E 's/^ +| +$//g')
  # Read the detail section out of whichever file the reference names.
  case "$det" in
    *' § '*) f="${det%% § *}"; h="${det#* § }" ;;
    *)       f="$DOC";         h="$det"        ;;
  esac
  sec=$(awk -v h="$h" '
    $0 ~ /^#{2,4} / { if (index($0, h)) {f=1; next} else if (f) {f=0} }
    f' "$f")
  for lbl in "Locator:" "Identity:" "Evidence:" "Rollback:"; do
    line=$(printf '%s\n' "$sec" | grep -F -- "$lbl" | head -1)
    if [ -z "$line" ]; then
      echo "FAIL: added seam section '$det' is missing the '$lbl' line"
      continue
    fi
    # The value after the label must be substantive, not an empty or stub field.
    val=$(printf '%s\n' "$line" | sed -E "s/^.*${lbl%:}: *//" | sed -E 's/[`*_]//g; s/^ +| +$//g')
    [ "${#val}" -ge 20 ] \
      || echo "FAIL: added seam '$det' has an empty or stub '$lbl' value: '$val'"
    printf '%s\n' "$val" | grep -qiE '^(n/a|none|tbd|todo|unknown)\.?$' \
      && echo "FAIL: added seam '$det' declares '$lbl' unanswered without justification"
  done
done | tee "${TMPDIR:-/tmp}/added-fields.log"
[ ! -s "${TMPDIR:-/tmp}/added-fields.log" ] || fail=1

# The six added seams are each named by a roster row (per D19). Missing one is
# not a soft warning: AC2 names them individually.
while IFS= read -r seam; do
  printf '%s\n' "$roster" | grep -qiF -- "$seam" \
    || say "added seam '$seam' has no roster row"
done <<'SEAMS'
permission guard
attempt-lifecycle ledger
sdd plan ledger
review-package store
ship-release state
wayfind state
SEAMS

# A80.1 - A80.4 appear in the coverage table with a real discharging heading.
for id in A80.1 A80.2 A80.3 A80.4; do
  row=$(printf '%s\n' "$cov" | grep -F -- "$id " | head -1)
  [ -n "$row" ] || { say "claim $id absent from the coverage table"; continue; }
  sec=$(printf '%s\n' "$row" | awk -F'|' '{print $5}' | sed -E 's/^ +| +$//g')
  printf '%s\n' "$heads" | grep -qxF -- "$sec" \
    || say "$id names discharging section '$sec', which is not a heading in $DOC"
done

# A80.1 specifics: the four adjudicated verbs, the boundary, the fail-closed classes.
while IFS= read -r lit; do
  grep -qF -- "$lit" "$DOC" || say "A80.1 missing literal: $lit"
done <<'LITS'
PreToolUse
git push
gh pr create
git branch -d
gh pr merge
fagenorn
elevenyellow
elevenyellow/nodocom
dev
enforce_admins
Nix Eval
GITHUB_TOKEN
no defer path
LITS
grep -qiF -- "forge-side" "$DOC" || say "A80.1's D14 boundary (forge-side enforcement) is not stated"

# A80.3 / V4: both full shas, their branches, and immutability proof.
# Each prototype is verified as a whole triple - sha, its exact remote branch,
# and the directory in that commit's tree - and the document must associate all
# three in one place. Checking them independently would pass a swapped pairing
# (per D19).
while IFS='|' read -r sha branch dir; do
  grep -qF -- "$sha" "$DOC" || say "prototype sha $sha is not recorded"
  grep -qF -- "$branch" "$DOC" || say "A80.3 does not name branch '$branch'"
  grep -qF -- "$dir" "$DOC" || say "A80.3 does not name directory '$dir'"
  git cat-file -e "${sha}^{commit}" 2>/dev/null \
    || say "V4: $sha is not a reachable commit object"
  # The sha must be the tip of that exact remote branch, not merely on some ref.
  actual=$(git ls-remote origin "refs/heads/$branch" | awk '{print $1}')
  [ "$actual" = "$sha" ] \
    || say "V4: origin/$branch is at '${actual:-<absent>}', not $sha"
  # The named directory must exist in that commit's tree.
  git ls-tree --name-only "$sha" -- "$dir" | grep -qx -- "$dir" \
    || say "V4: '$dir' is not in the tree of $sha"
  # The document must state the three together, within one block, not scattered.
  awk -v s="$sha" -v b="$branch" -v d="$dir" '
    { buf[NR]=$0 }
    END {
      for (i=1; i<=NR; i++) {
        w=""
        for (j=i; j<=NR && j<i+12; j++) w = w "\n" buf[j]
        if (index(w,s) && index(w,b) && index(w,d)) { print "OK"; exit }
      }
    }' "$DOC" | grep -qx OK \
    || say "A80.3 does not associate $sha with '$branch' and '$dir' in one place"
done <<'PROTOS'
dc98ba9b6bafaf7b5373cc7595ef79a5526846d1|worktree-prototype-release-transactions|prototype-release-transactions
b49c8771cbaf87eefc5f0d385100e205060538d9|worktree-prototype-nix-config-adoption-dry-run|prototype-agent-adoption-dry-run
PROTOS

# A80.4: the #86 correction is present, and no tracker comment was edited.
grep -qE '^#{2,4} .*[Cc]orrection' "$DOC" || say "A80.4 has no named correction subsection"
grep -qF -- '#86' "$DOC" || say "A80.4 does not name issue #86"
grep -qF -- 'git ls-remote origin' "$DOC" || say "A80.4 does not give the ls-remote evidence"

# .superpowers/ is declared historical.
grep -qF -- '.superpowers/' "$DOC" || say "the durable-state locators do not use the literal .superpowers/ paths"
grep -qiF -- 'Superpowers' "$DOC" || say "the historical-name note is absent"

if grep -qE '\b(TODO|TBD|FIXME)\b' "$DOC"; then say "placeholder marker in $DOC"; fi

git show "HEAD:$DOC" >/dev/null 2>&1 || say "V1: $DOC is not committed at HEAD"

[ "$fail" -eq 0 ] && echo "PASS gate-80b"
exit "$fail"
```

Save this to `"${TMPDIR:-/tmp}/gate-package.sh"` — the whole-package sweep.

```bash
#!/usr/bin/env bash
set -uo pipefail
fail=0
say() { echo "FAIL: $*"; fail=1; }
S=".claude/specs"

# V1 for all four, at HEAD.
for d in 2026-08-20-cross-agent-project-surfaces-research \
         2026-08-20-agent-fallback-inventory-research \
         2026-08-20-project-knowledge-inventory-research \
         2026-08-20-release-lifecycle-seams-research; do
  git show "HEAD:$S/$d.md" >/dev/null 2>&1 || say "V1: $S/$d.md is not committed at HEAD"
done

# V2 across the package: every claim ID appears in the right root AND its
# fourth column resolves to a real heading — in that root when named bare, and
# in the named evidence member when written `<member path> § <heading>` (D22).
# Presence alone was never the seam; a row pointing at nothing covers nothing.
check() {
  doc="$S/$1.md"; shift
  cov=$(awk '/^## Coverage of the resolution summary$/{f=1;next} /^#{2,4} /{f=0} f' "$doc" \
    | grep '^|' | grep -v '^| *ID' | grep -vE '^\|[ :|-]+\|$')
  dheads=$(grep -E '^#{2,4} ' "$doc" | sed -E 's/^#{2,4} //')
  for id in "$@"; do
    row=$(printf '%s\n' "$cov" | grep -F -- "| $id " | head -1)
    [ -n "$row" ] || { say "$doc does not cover $id"; continue; }
    ref=$(printf '%s\n' "$row" | awk -F'|' '{print $5}' | sed -E 's/^ +| +$//g')
    case "$ref" in
      *' § '*)
        f="${ref%% § *}"; h="${ref#* § }"
        [ -f "$f" ] || { say "$doc row $id names missing member '$f'"; continue; }
        grep -E '^#{2,4} ' "$f" | sed -E 's/^#{2,4} //' | grep -qxF -- "$h" \
          || say "$doc row $id: '$h' is not a heading in $f" ;;
      *)
        printf '%s\n' "$dheads" | grep -qxF -- "$ref" \
          || say "$doc row $id: '$ref' is not a heading in $doc" ;;
    esac
  done
}
check 2026-08-20-cross-agent-project-surfaces-research C60.1 C60.2 C60.3 C60.4 C60.5
check 2026-08-20-agent-fallback-inventory-research C61.1 C61.2 C61.3 C61.4 C61.5
check 2026-08-20-project-knowledge-inventory-research C62.1 C62.2 C62.3 C62.4 C62.5 C62.6
check 2026-08-20-release-lifecycle-seams-research \
  C80.1 C80.2 C80.3 C80.4 C80.5 C80.6 A80.1 A80.2 A80.3 A80.4

# Shared contract literals in all four.
for d in 2026-08-20-cross-agent-project-surfaces-research \
         2026-08-20-agent-fallback-inventory-research \
         2026-08-20-project-knowledge-inventory-research \
         2026-08-20-release-lifecycle-seams-research; do
  doc="$S/$d.md"
  for lit in '**Durability: committed**' '## Provenance' '## Research question' \
             '## Coverage of the resolution summary' '## Unverified inheritance' \
             '## What this document does not decide' \
             'Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked'; do
    grep -qF -- "$lit" "$doc" || say "$doc is missing the shared literal: $lit"
  done
  if grep -qE '\b(TODO|TBD|FIXME)\b' "$doc"; then say "placeholder marker in $doc"; fi
done

# Scope: this branch touches only .claude/specs and .claude/plans.
BASE=$(git merge-base HEAD origin/main)
if git diff --name-only "$BASE..HEAD" | grep -vE '^\.claude/(specs|plans)/'; then
  say "the branch touches files outside .claude/specs and .claude/plans"
fi

[ "$fail" -eq 0 ] && echo "PASS gate-package"
exit "$fail"
```

- [ ] **Step 2: Run both gates and watch them fail**

Run: `bash "${TMPDIR:-/tmp}/gate-80b.sh"; bash "${TMPDIR:-/tmp}/gate-package.sh"`
Expected at this task's base commit (Task 4's commit): `gate-80b.sh` **FAILS**
with at least
`FAIL: roster has 0 'enforcement seam' rows, expected 1` and
`FAIL: roster has 0 'durable-state seam' rows, expected 5`, plus the four
`claim A80.n absent from the coverage table` lines — Task 4 wrote the
release-unit half only, so those rows provably do not exist yet.
`gate-package.sh` fails its `does not cover A80.1` checks for the same reason.
Both exit non-zero.

- [ ] **Step 3: Gather the primary sources for the six added seams**

**The enforcement seam (`A80.1`)** — read the `PreToolUse` hook block in
`home/common/claude-code/default.nix` (the hook definition begins near the
`hooks.PreToolUse` attribute) together with `tests/test_claude_permission_guard.py`
and `CLAUDE.md`'s Claude Code section. Derive from the source, not from
`CLAUDE.md`'s summary: the four adjudicated lifecycle verbs and the exact
validated form of each; the authorized-owner set and where it is declared; the
per-repository integration-base map including `dev` for `elevenyellow/nodocom`
and its deliberate exemption from the protection demand; the live checks against
a default-branch base (an open PR on that base, at least one required status
context, `enforce_admins` enabled); the scrubbing of `GITHUB_TOKEN`/`GH_TOKEN`
from the lookups' environment so they authenticate through the gh keyring
credential; the fail-closed classes (unparseable command, shell handed to an
evaluator, a guarded verb outside a command position, unresolvable repo or
default branch, child timeout, non-zero or unparseable output); and the absence
of a defer path. Cross-check the forge side in `.github/branch-protection.json`
and `.github/workflows/ci.yaml` for the D14 boundary.

**The five durable-state seams (`A80.2`)** — read each system's own source and
record its literal path template:

1. the attempt-lifecycle ledger — `home/common/agent-skills/scripts/workflow-state.py`
   and `home/common/agent-skills/skills/from-issue/SKILL.md`;
2. the sdd plan ledger — `home/common/agent-skills/skills/sdd/scripts/sdd-workspace`
   for the actual bucket and path derivation, with
   `home/common/agent-skills/skills/sdd/SKILL.md` for its contract;
3. the review-package store — `home/common/agent-skills/skills/sdd/scripts/review-package`
   is the primary source: it derives the durable locator and identity from the
   primary checkout, the issue, the run/branch identity, the producer and the
   head SHA. Read it before the skill prose in
   `home/common/agent-skills/skills/sdd/SKILL.md` and
   `home/common/agent-skills/skills/ship-issue/SKILL.md`;
4. ship-release's own state file —
   `home/common/agent-skills/skills/ship-release/SKILL.md`;
5. the tracker-native wayfind state —
   `home/common/agent-skills/skills/wayfind/SKILL.md`.

`CLAUDE.md`'s paragraph on the `.superpowers/` paths names which root each is
rooted at; confirm each against the skill source before writing it.

**The prototype references (`A80.3`, `A80.4`)** — run, and paste the real
output into the document's evidence:

```bash
git cat-file -e dc98ba9b6bafaf7b5373cc7595ef79a5526846d1^{commit} && echo reachable
git cat-file -e b49c8771cbaf87eefc5f0d385100e205060538d9^{commit} && echo reachable
git ls-remote origin | grep prototype
git ls-tree --name-only dc98ba9b6bafaf7b5373cc7595ef79a5526846d1 | grep prototype
git ls-tree --name-only b49c8771cbaf87eefc5f0d385100e205060538d9 | grep prototype
unset GITHUB_TOKEN GH_TOKEN && gh issue view 86 --repo fagenorn/nix-config --comments
```

- [ ] **Step 4: Extend the document**

Append to `.claude/specs/2026-08-20-release-lifecycle-seams-research.md`,
leaving Task 4's release-unit content untouched:

- six new roster rows — one `enforcement seam`, five `durable-state seam` —
  each naming its detail heading in the `Detail` column;
- a detail section per added seam, each with the four label lines `Locator:`,
  `Identity:`, `Evidence:`, `Rollback:`;
- the bounded "only machine enforcement" statement and the forge-side contrast
  (`A80.1`, per D14);
- the two prototype references with full shas, `origin` branches, directories,
  retrievability commands and the real command output (`A80.3`);
- a named correction subsection for #86 (`A80.4`, per D7);
- the `.superpowers/`-is-historical note;
- four new coverage rows for `A80.1`–`A80.4`, each naming a real heading.

Run: `bash "${TMPDIR:-/tmp}/gate-80b.sh"`
Expected: `gate-80b` exits 1 with exactly one `FAIL:` line, the V1 line
`FAIL: V1: <doc> is not committed at HEAD`. Every content check passes here;
V1 cannot pass before Step 5's commit, so `PASS` is unreachable at this step.
If any other `FAIL:` line appears, fix the document and re-run before
committing.

- [ ] **Step 5: Commit, then run the whole-package sweep**

Stage the whole #80 package, not just the root: if this task put any evidence
into a new member, an untracked member leaves every reference to it dangling
after the commit and the branch ships a broken package.

```bash
git add .claude/specs/2026-08-20-release-lifecycle-seams-research.md \
        .claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/
git status --porcelain -- .claude/specs   # must show nothing untracked
git commit -m "$(cat <<'MSG'
docs(specs): add the #80 enforcement and durable-state seams and the #86 correction

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
)"
bash "${TMPDIR:-/tmp}/gate-80b.sh"
bash "${TMPDIR:-/tmp}/gate-package.sh"

# V6 — packageability, after the commit. Always pass --output: the default
# destination is the very range the mandatory final review publishes to, and
# review-package publishes exclusively, so a default-path run here makes the
# final review's own generation fail and re-running does not clear it.
OUT=$(mktemp -d)
review-package .claude/plans/2026-09-02-issue-115-recovered-wayfind-findings.md \
  "$(git merge-base origin/main HEAD)" HEAD "$OUT/v6.json"
# The destination is the fourth positional argument; in diff mode --output is
# rejected as an invalid invocation. Require exit 0 and within_budget, then:
rm -rf "$OUT"
```

Expected: nothing untracked under `.claude/specs`; the commit is SSH-signed and
succeeds; both gates print their `PASS` line and exit 0; V6 exits 0 with
`within_budget`. If V6 exits 3, this task's additions pushed a file or the
package over — move the bulkiest new evidence into a member under
`.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/` following
Task 5's conventions, keeping the conclusions in the root, and re-run. AC4's `git show main:<path>` form of V1 becomes true when this
branch merges (per D16); nothing further in this plan can assert it.

- [ ] **Step 6: V5 — source-backed semantic audit (per D19)**

The gate has proven traceability only. Before this task is done, read the
document against its cited sources and confirm each claim ID it owes is
*answered*, not merely *addressed*:

- Open every `##`/`###` section the coverage table names, and every live source
  that section cites. A citation that does not support the sentence it anchors
  is a rejection.
- Confirm each enumerated obligation this task's invariants list — every matrix
  cell, every mandated axis, every required field — is answered in the place the
  coverage table points at. The gate's document-wide `grep` cannot see whether an
  axis is answered in *each* cell; only this reading can.
- A field with no answer in the live tree must say so explicitly. Silence and
  plausible-but-uncited prose are both rejections.
- Reject any conclusion not traceable to a source read during Step 3.

Expected: every claim ID answered from a cited source, or the document revised
and Steps 4-5 re-run.

---

**Amendment (2026-09-02, D22).** Task 4's reopened Step 7 decomposes the #80
document into a root plus evidence members before this task runs, and leaves
that root at or under 35,000 bytes so your four sections have room. Append them
to the **root**. If a section's evidence is bulky enough to push any file past
V6's 65,536-byte cap, move that evidence into a new member under
`.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/`, following
the conventions Task 5 sets out, and keep the section's conclusions in the root.
**Watch the shard budget.** The branch already fills 8 of `review-package`'s 8
shards, and shards hold whole files, so your additions can fail V6 on
`member_count` rather than on any file being too big. Task 5's `Shard budget`
invariant explains the packing and is worth reading before you decide whether
your evidence goes in the root or a member. If V6 exits 3 on `member_count`,
resize or relocate your additions and redo; if nothing passes, report `BLOCKED`
with what you tried.

Every heading reference you write obeys D22's two forms — bare for a root
heading, `<member repo-relative path> § <heading text>` for a member one — and
Step 1's `resolve` helper is what checks them. Run V6 as the last gate of this
task, not only V1–V4. The spec's `## Amendment log` records the back-up from
Phase 6 to planning that produced D22.
