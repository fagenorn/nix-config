# Task 4: #80 — release-unit seams and the inherited claims

**Files:**
- Create: `.claude/specs/2026-08-20-release-lifecycle-seams-research.md`
- Test: none — this repository has no test suite for documentation. The task's
  gate is the shell block in Step 2/Step 4, run from the worktree root.

**Interfaces:**

- Consumes: the spec
  `.claude/specs/2026-09-02-issue-115-recovered-wayfind-findings-design.md` —
  its `## Document contract`, the **inherited claims** half of its
  `### .claude/specs/2026-08-20-release-lifecycle-seams-research.md (#80)`
  table (`C80.1`–`C80.6`), its `## Seam taxonomy` and its
  `**Terminology guards for #80**`, and rows D1–D6, D8, D10, D11, D12, D13,
  D17. The plan root's `## Global Constraints` and canonical section names. The
  canonical document shape Task 1 produces: the ordered headings
  `## Provenance`, `## Research question`,
  `## Coverage of the resolution summary`, `## Unverified inheritance`, body
  sections, `## What this document does not decide` last; a four-column
  coverage table whose fourth column is the verbatim text of a `##`/`###`
  heading in the same document; and the front-matter literals
  `**Durability: committed**` and
  ``Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked``.
- Produces, for Task 5 to extend in the same file:
  - a `## Seam roster` section holding **one** table with exactly three
    columns, `| Seam | Class | Detail |`: `Class` carries exactly one of the
    three literals `release-unit seam`, `enforcement seam`,
    `durable-state seam`; `Detail` carries the verbatim text of a `##`/`###`
    heading **in the same document** that holds that seam's fields. All five
    `release-unit seam` rows are filled in by this task; Task 5 appends the one
    `enforcement seam` row and the five `durable-state seam` rows to this same
    table.
  - a `### Field definitions` subsection under `## Seam roster` defining
    **locator**, **identity**, **evidence** and **rollback** inline exactly as
    the spec's seam taxonomy defines them, and stating that a seam in either
    added class records them as four label lines — `Locator:`, `Identity:`,
    `Evidence:`, `Rollback:` — in its own detail section. `locator` names its
    root explicitly (caller-supplied repository root, primary checkout, feature
    worktree, `$TMPDIR`, or the tracker itself).
  - one subsection per release unit, each named in the roster's `Seam` column
    verbatim, carrying the full `C80.4` recording list.

**Invariants:**

- The path is exactly the path #80's resolution comment links; the
  `2026-08-20` prefix is #80's decision date, not the authorship date.
- `## Provenance` declares the re-derivation exactly as D1 requires, **and**
  additionally carries the D2 clause: #80's instruction asked for an `attached`
  file and this is a `committed` one.
- **Primary sources only** (per D6). The resolution summary is the coverage
  floor and is never cited as a source. Every release-unit fact is derived from
  a file in this repository, in `/Users/anis/Projects/nodocom` or in
  `/Users/anis/Projects/argus`, cited with the repository name, repo-relative
  path, the checkout's observed `HEAD` sha and the observation date (per D3).
  Both fleet checkouts are read-only.
- **Terminology guards** (per D10), each disambiguated in one line where first
  used: *state* — #82/#88's release state and terminal receipt versus the
  workflow skills' durable state stores; *identity* — #88's expected/running
  **subject identity** versus a state record's key, with every seam row saying
  which sense it uses; *seam* — used only through the roster's three declared
  classes, and the document never implies a non-release-unit seam is a release
  unit.
- Each of the five release units carries **every** field of `C80.4`: candidate
  and release identity; publication target, trigger, ordering, immutability;
  activation mode, authority boundary, restart/convergence; deployment-success,
  running-identity, liveness, readiness, migration and product-smoke evidence;
  durable or mutable data at risk; rollback anchor, action, reversibility limit,
  retirement evidence; and partial-failure and re-entry behaviour already
  implemented or documented. A field with no answer in a given unit says so
  explicitly and why; a blank cell is a defect.
- `C80.5` holds: facts shared by all three projects live in their own section,
  separate from project-specific mechanics.
- `C80.6` holds: the architecture is not chosen and no universal adapter is
  invented. The document ends with `## What this document does not decide`.
- Length is governed by the-bar's *Token economy*; `artifact-budget` is never
  run against this file (per D8).

- [ ] **Step 1: Write the gate first, before the document**

Save this to `"${TMPDIR:-/tmp}/gate-80a.sh"`. It is the task's contract.

```bash
#!/usr/bin/env bash
set -uo pipefail
DOC=".claude/specs/2026-08-20-release-lifecycle-seams-research.md"
fail=0
say() { echo "FAIL: $*"; fail=1; }
count() { c=$(grep -oiF -- "$1" "$DOC" | wc -l | tr -d ' '); echo "${c:-0}"; }

test -f "$DOC" || { echo "FAIL: $DOC does not exist"; exit 1; }

while IFS= read -r lit; do
  grep -qF -- "$lit" "$DOC" || say "missing literal: $lit"
done <<'LITS'
**Durability: committed**
## Provenance
re-derivation
2026-09-02
issue #115
never committed
unrecoverable
attached
Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked
## Research question
## Coverage of the resolution summary
## Unverified inheritance
## Seam roster
### Field definitions
release-unit seam
enforcement seam
durable-state seam
locator
subject identity
## What this document does not decide
LITS

order=$(grep -n '^## ' "$DOC" | sed 's/^[0-9]*://')
expected=$'## Provenance\n## Research question\n## Coverage of the resolution summary\n## Unverified inheritance'
printf '%s\n' "$order" | head -4 | diff -q - <(printf '%s\n' "$expected") >/dev/null \
  || say "the first four ## headings are not the canonical four, in order"
[ "$(printf '%s\n' "$order" | tail -1)" = "## What this document does not decide" ] \
  || say "the last ## heading is not 'What this document does not decide'"

cov=$(awk '/^## Coverage of the resolution summary$/{f=1;next} /^## /{f=0} f' "$DOC")
heads=$(grep -E '^#{2,4} ' "$DOC" | sed -E 's/^#{2,4} //')
for id in C80.1 C80.2 C80.3 C80.4 C80.5 C80.6; do
  row=$(printf '%s\n' "$cov" | grep -F -- "$id " | head -1)
  [ -n "$row" ] || { say "claim $id absent from the coverage table"; continue; }
  n=$(printf '%s\n' "$row" | awk -F'|' '{print NF}')
  [ "$n" -ge 6 ] || say "$id row does not have four columns"
  printf '%s\n' "$row" | grep -qE "$id \((summary|question)\)" \
    || say "$id row does not carry its (summary|question) source tag"
  sec=$(printf '%s\n' "$row" | awk -F'|' '{print $5}' | sed -E 's/^ +| +$//g')
  [ -n "$sec" ] || { say "$id row names no discharging section"; continue; }
  printf '%s\n' "$heads" | grep -qxF -- "$sec" \
    || say "$id names discharging section '$sec', which is not a heading in $DOC"
done

# Exactly five release-unit rows in the roster.
roster=$(awk '/^## Seam roster$/{f=1;next} /^## /{f=0} f' "$DOC")
ru=$(printf '%s\n' "$roster" | grep -cF 'release-unit seam' || true)
[ "$ru" -eq 5 ] || say "the roster has $ru 'release-unit seam' rows, expected exactly 5"

# Every roster row's Detail column names a real heading in this document.
printf '%s\n' "$roster" | grep -F ' seam ' | while IFS= read -r row; do
  det=$(printf '%s\n' "$row" | awk -F'|' '{print $4}' | sed -E 's/^ +| +$//g')
  [ -n "$det" ] || { echo "FAIL: a roster row names no Detail section"; continue; }
  printf '%s\n' "$heads" | grep -qxF -- "$det" \
    || echo "FAIL: roster Detail '$det' is not a heading in $DOC"
done | tee "${TMPDIR:-/tmp}/roster-detail.log"
[ ! -s "${TMPDIR:-/tmp}/roster-detail.log" ] || fail=1

# The five release-unit families are present.
for u in "Nix host generation" Railway GHCR reconciler launchd sign; do
  grep -qiF -- "$u" "$DOC" || say "release unit keyword '$u' is absent"
done

# Every C80.4 field is answered once per release unit (>= 5 occurrences each).
while IFS= read -r field; do
  n=$(count "$field")
  [ "$n" -ge 5 ] || say "C80.4 field '$field' appears $n times; expected >= 5 (one per release unit)"
done <<'FIELDS'
release identity
publication target
immutability
activation mode
authority boundary
liveness
readiness
migration
rollback anchor
reversibility limit
retirement evidence
re-entry
FIELDS

# Shared facts are separated from project-specific mechanics (C80.5).
grep -qE '^#{2,4} .*[Ss]hared' "$DOC" || say "no section separating facts shared by all three projects"

# All three repositories are cited with an observed HEAD (D3, D6).
for r in nix-config nodocom argus; do
  grep -qiF -- "$r" "$DOC" || say "repository '$r' is not cited"
done
grep -qiE 'HEAD [`(]?[0-9a-f]{7,40}' "$DOC" || say "no checkout HEAD sha recorded for the fleet citations"

if grep -qE '\b(TODO|TBD|FIXME)\b' "$DOC"; then say "placeholder marker in $DOC"; fi
if grep -qiE 'restoration of the original|restored (from|the) original' "$DOC"; then
  say "$DOC claims to restore the original"
fi

git show "HEAD:$DOC" >/dev/null 2>&1 || say "V1: $DOC is not committed at HEAD"

[ "$fail" -eq 0 ] && echo "PASS"
exit "$fail"
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `bash "${TMPDIR:-/tmp}/gate-80a.sh"`
Expected at this task's base commit: **FAIL** — first line
`FAIL: .claude/specs/2026-08-20-release-lifecycle-seams-research.md does not exist`,
exit status 1. That path has never existed on any git ref
(`git log --all -- <path>` returns zero commits), so the observation holds at
base.

- [ ] **Step 3: Gather the primary sources**

Read #80's resolution comment and research question first —
`unset GITHUB_TOKEN GH_TOKEN && gh issue view 80 --repo fagenorn/nix-config --comments`
— and transcribe the question verbatim under `## Research question`. Treat the
summary as the coverage floor only, never as a source (per D6). Then, per
release unit:

1. **Nix host generations**, this repository: `flake.nix`, `lib/helpers.nix`,
   `justfile` (`build`, `switch`, `gc`), `hosts/common/`, and `CLAUDE.md`'s
   Commands and branch-protection sections.
2. **Railway API/admin services**, `/Users/anis/Projects/nodocom` (read-only):
   the Railway configuration files and whatever declares service deployment.
3. **Digest-addressed GHCR engines with reconciler convergence**,
   `/Users/anis/Projects/nodocom` (read-only): the GHCR publish-and-roll
   workflow and the reconciler supervisor.
4. **The Argus launchd daemon rooted in a checkout**,
   `/Users/anis/Projects/argus` (read-only): `daemon/launchd.ts`.
5. **Locally signed Argus helpers**, `/Users/anis/Projects/argus` (read-only):
   `daemon/sign.sh`.

Record `git rev-parse HEAD` and the observation date for each fleet checkout
before citing anything from it.

- [ ] **Step 4: Write the document, then re-run the gate**

Write the document with, at minimum: the canonical front matter plus D2's
changed-durability clause; the coverage table for `C80.1`–`C80.6`; the
`## Seam roster` with its `### Field definitions` and its five
`release-unit seam` rows; one subsection per release unit carrying the full
`C80.4` recording list; the identity and evidence contrasts of `C80.2`; the
rollback spectrum of `C80.3`; a section holding the facts shared by all three
projects, separate from project-specific mechanics (`C80.5`); and a closing
`## What this document does not decide` recording that no architecture is
chosen and no universal adapter is invented (`C80.6`).

Run: `bash "${TMPDIR:-/tmp}/gate-80a.sh"`
Expected: `PASS`, exit 0. (V1 still fails until Step 5's commit; re-run after
committing.)

- [ ] **Step 5: Commit, then confirm V1**

```bash
git add .claude/specs/2026-08-20-release-lifecycle-seams-research.md
git commit -m "$(cat <<'MSG'
docs(specs): re-derive the #80 release-unit seams from primary sources

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
)"
bash "${TMPDIR:-/tmp}/gate-80a.sh"
```

Expected: the commit is SSH-signed and succeeds; the gate prints `PASS` with
exit 0, V1 included.
