# Task 5: decompose the #61 and #80 documents into root-plus-evidence-member packages

**Files:**
- Modify: `.claude/specs/2026-08-20-agent-fallback-inventory-research.md` (#61 root)
- Modify: `.claude/specs/2026-08-20-release-lifecycle-seams-research.md` (#80 root)
- Create: one or more members under
  `.claude/specs/2026-08-20-agent-fallback-inventory-research.evidence/`
- Create: one or more members under
  `.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/`
- Test: none — this repository has no test suite for documentation. The task's
  gates are the shell blocks in Step 4, run from the worktree root.

**Why this task exists.** Read the plan root's `## Amendment log` before
starting. This is not a content task. Tasks 1–4 produced correct, reviewed
documents that the mandatory final two-axis review cannot package, because
`review-package` refuses an individually oversized handwritten file diff and has
no remediation for that violation. Your job is to change the *delivery shape*
so the same content becomes reviewable, and to change nothing else.

**Interfaces:**

- Consumes: the plan root's `## Global Constraints` (especially
  **Coverage-table shape** and **Review-package bound**), its `## Test seams`
  V1, V2 and V6, and spec rows D3, D12, D19 and D22.
- Produces, for Task 6 to extend: a #80 root small enough to receive Task 6's
  four sections and stay under the 55,000-byte bound, and an evidence-member
  convention Task 6 follows for its own bulk evidence.

**Invariants:**

- **No sentence changes meaning.** Every block you relocate moves
  byte-identical, apart from heading-level normalisation where a `###` becomes
  the member's own `##`. You are not rewriting, summarising, correcting or
  extending any finding. If you believe a sentence is wrong, do not fix it —
  record it in your report and leave it. Five fix rounds settled this prose and
  a silent edit here would be indistinguishable from the failure this issue
  exists to repair.
- **No published number moves.** Every count, byte figure, percentage and total
  keeps its value. After the move, re-grep each root for the figures it still
  cites and confirm each still resolves to content the reader can reach.
- **The roots keep their paths and their conclusions.** The two roots stay at
  the exact paths #61's and #80's resolution comments link. A root always keeps,
  in the canonical order, `## Provenance`, `## Research question`,
  `## Coverage of the resolution summary`, `## Unverified inheritance`, every
  synthesis and conclusion sentence, and `## What this document does not decide`
  last. Only bulk evidence — per-hit maps, per-invocation appendices, per-unit
  recording tables — is eligible to move.
- **Every member is reachable and self-describing.** At the point a block leaves
  a root, the root keeps a heading and a pointer line naming the member's
  repo-relative path and what it contains, so no reader hits a gap. Each member
  opens with a one-paragraph header naming its root, stating that it is an
  evidence member of that document and carries no conclusion of its own, and
  declaring the same `2026-09-02` re-derivation provenance the root declares
  (per D1 — a member found on its own must not read as an independent finding).
- **Coverage rows point at what discharges them.** Where a discharging heading
  moves into a member, that coverage row's fourth column becomes
  `<member repo-relative path> § <verbatim heading text>` (per D22). Where the
  heading stays in the root, the row is untouched. The same rule applies to the
  #80 `## Seam roster` table's `Detail` column, which Task 4 built under the
  superseded in-the-same-document rule.
- **Byte bounds.** After this task, every file this branch adds has a
  whole-file diff over the merge base of at most **55,000 bytes**. The #80 root
  is additionally held to at most **35,000 bytes**, because Task 6 still has
  four sections to append to it.
- Commits are SSH-signed and carry the
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer. Never pass
  `--no-gpg-sign`.

**Steps:**

- [ ] **Step 1 — measure before touching anything.** From the worktree root,
      record the merge base and each file's current whole-file diff size:

      MB=$(git merge-base origin/main HEAD)
      for f in $(git diff --name-only "$MB"..HEAD); do
        printf '%s %s\n' "$(git diff --no-ext-diff --binary -U10 "$MB"..HEAD -- "$f" | wc -c)" "$f"
      done | sort -rn

      Two files exceed 65,536. Those two are your only subjects. Write the
      starting numbers into your report.

- [ ] **Step 2 — choose the cuts.** For each of the two roots, list its
      `##`/`###` headings with their byte extents, then choose the smallest set
      of bulk-evidence blocks whose removal brings the root under its bound.
      Prefer few, large, self-contained blocks over many small ones: each member
      is a whole file to the shard packer, and the whole-branch package must
      still fit eight shards. For #80, the per-release-unit mechanics detail is
      the natural member and is what makes the 35,000-byte root bound
      reachable. For #61, the per-hit adjudication map and the measured-range
      appendix are the natural members. Do not cut a block that contains a
      synthesis or conclusion sentence; if a candidate block mixes evidence and
      conclusion, leave the conclusion in the root and move only the table.
      Record the chosen cuts and their sizes in your report before editing.

- [ ] **Step 3 — perform the moves.** For each cut: create the member, write its
      header paragraph, append the block byte-identical, and replace the block
      in the root with its retained heading plus the pointer line. Then update
      every coverage row and every `## Seam roster` `Detail` cell whose heading
      moved, and every in-document cross-reference that named a moved heading.
      Commit each document's decomposition separately, so a reviewer can read
      one at a time.

- [ ] **Step 4 — verify.** All four blocks must pass before you report DONE.

      # V1 — the four linked roots still resolve at this commit
      for p in .claude/specs/2026-08-20-cross-agent-project-surfaces-research.md \
               .claude/specs/2026-08-20-agent-fallback-inventory-research.md \
               .claude/specs/2026-08-20-project-knowledge-inventory-research.md \
               .claude/specs/2026-08-20-release-lifecycle-seams-research.md; do
        git show "HEAD:$p" > /dev/null || echo "MISSING $p"
      done

      # V2 — every coverage row's fourth column resolves to a real heading,
      # in the root when named bare and in the member when named `path § heading`
      # (write this check as a script in your report; it must open the named
      # file and match the heading text character-for-character)

      # V6 — the decisive gate
      review-package .claude/plans/2026-09-02-issue-115-recovered-wayfind-findings.md \
        "$(git merge-base origin/main HEAD)" HEAD

      V6 must exit 0 with `budget_status` `within_budget`. Exit 3 means a file
      is still over; exit 2 with `review package generation failed` is a stale
      package directory from an earlier run against this same range, not a
      budget verdict — re-run against the current `HEAD`.

- [ ] **Step 5 — report.** Report the before and after byte table, the cuts you
      chose and why, the coverage rows you rewrote, the V6 result, and anything
      you noticed but deliberately did not fix.

**Verification:** V1 passes for all four roots; V2 passes for every coverage row
in both decomposed packages; V6 exits 0 with `within_budget`; `git diff` shows
no changed sentence outside pointer lines, member headers, coverage-row fourth
columns and roster `Detail` cells.
