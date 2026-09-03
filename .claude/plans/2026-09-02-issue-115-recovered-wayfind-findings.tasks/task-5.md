# Task 5: decompose the #61 document into a root-plus-evidence-member package

**Files:**
- Modify: `.claude/specs/2026-08-20-agent-fallback-inventory-research.md` (the #61 root)
- Create: one or more members under
  `.claude/specs/2026-08-20-agent-fallback-inventory-research.evidence/`
- Test: none — this repository has no test suite for documentation. The task's
  gates are the shell blocks in Step 5, run from the worktree root.

**Why this task exists.** Read the spec's `## Amendment log` and D22 before
starting. This is not a content task. Task 2 produced a correct, reviewed
document that the mandatory final two-axis review cannot package, because
`review-package` shards a diff into whole files and refuses an individually
oversized handwritten file diff with no remediation available. Measured over
the merge base at `7edbe6b`, this document's whole-file diff is 80,800 bytes
against a 65,536-byte per-member cap. Your job is to change the *delivery shape*
so the same bytes become reviewable, and to change nothing else. Task 4 does the
same for the #80 document; this task and that one share the D22 conventions and
must produce the same shapes.

**Interfaces:**

- Consumes: the spec's D3, D12, D19 and D22; the plan root's `## Global
  Constraints` (especially **Coverage-table shape** and **Review-package
  bound**) and its `## Test seams` V1, V2 and V6.
- Produces: a #61 package whose root and every member pass V6, and the pointer,
  member-header and coverage-reference conventions Task 4 and Task 6 reuse.

**Invariants:**

- **No sentence changes meaning.** Every relocated block moves byte-identical,
  apart from the heading-level normalisation Step 3 permits. You are not
  rewriting, summarising, correcting or extending any finding. If you believe a
  sentence is wrong, do not fix it — record it in your report and leave it. Five
  fix rounds settled this prose; a silent edit here would be indistinguishable
  from the failure this issue exists to repair. Step 5's `cmp` gate is what
  proves this, not your reading.
- **Only bulk evidence moves** (per D22): a per-hit adjudication map, a
  per-invocation appendix, or a comparable block whose value is enumeration
  rather than argument. A member never carries a synthesis, a conclusion, or a
  sentence the document reasons from.
- **The root keeps its path and its argument.** It stays at
  `.claude/specs/2026-08-20-agent-fallback-inventory-research.md`, the exact
  path #61's resolution comment links, and keeps in canonical order
  `## Provenance`, `## Research question`,
  `## Coverage of the resolution summary`, `## Unverified inheritance`, every
  synthesis and conclusion, and `## What this document does not decide` last.
- **Every member is reachable and self-describing.** Where a block leaves the
  root, the root keeps a heading plus a pointer line naming the member's
  repo-relative path and what it holds, so no reader hits a gap. Each member
  opens with a one-paragraph header naming its root, stating it is an evidence
  member carrying no conclusion of its own, and declaring the same 2026-09-02
  re-derivation provenance the root declares (per D1) — a member found alone
  must not read as an independent finding.
- **Coverage rows point at what discharges them.** Where a discharging heading
  moves into a member, that row's fourth column becomes
  `<member repo-relative path> § <verbatim heading text>` (per D22). Where the
  heading stays in the root, the row is untouched.
- **Byte bounds.** V6 is the arbiter and the only bound this task asserts: after
  this task every file the branch adds must satisfy it. Aim to land the root and
  each member near 45,000–55,000 bytes rather than just under the 65,536-byte
  cap: shards hold whole files, so slack is what keeps the package inside its
  eight-shard limit once Task 6 adds its content.
- **Shard budget — read this before choosing your split sizes.** V6 has two
  ways to fail and the second one is now the live risk. After Task 4's
  decomposition the branch already fills **8 of `review-package`'s 8 shards**,
  with 404,249 of 524,288 aggregate bytes. Shards hold whole files and the
  version-1 packer merely groups *adjacent* files in path order, so a large
  file that will not fit beside its neighbour opens a shard and wastes the
  remainder. Splitting one file into two therefore adds a file to a packing
  problem that is already at its limit, and a careless split pushes the count to
  9 and fails on `member_count`.

  Two things work in your favour. The producer retries a `member_count`-only
  failure as interface version 3, which repacks with *first fit* rather than
  adjacency and is markedly better. And your two output sizes are yours to
  choose: your member sorts immediately before your root, both land between
  `task-6.md` and the #60 document, and a member near **22,000 bytes** packs
  into the shard those task members leave part-empty, while a root up to about
  **60,000** then takes a shard of its own. Sizes near the middle — two files of
  roughly 40,000 — are the worst case, because neither pairs with anything.

  This is engineering against a measured limit, not a rule of thumb. Compute the
  packing before you commit, and treat V6 as the arbiter: if it exits 3 on
  `member_count`, change the split sizes and redo the move rather than accepting
  it. If no split you can find passes, stop and report `BLOCKED` with the sizes
  you tried and the packing each produced — that is a real finding about the
  branch, not a failure of yours.
- Commits are SSH-signed and carry the
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer. Never pass
  `--no-gpg-sign`.

**Steps:**

- [ ] **Step 1 — pin the baseline.** Before editing anything:

      MOVE_BASE=$(git rev-parse HEAD)
      MB=$(git merge-base origin/main HEAD)
      DOC=.claude/specs/2026-08-20-agent-fallback-inventory-research.md
      git diff --no-ext-diff --binary -U10 "$MB"..HEAD -- "$DOC" | wc -c

      Record `MOVE_BASE`, `MB` and that byte count in your report. `MOVE_BASE`
      is the immutable copy every later comparison reads; never compare against
      the working tree.

- [ ] **Step 2 — choose the cuts.** List the document's `##`/`###` headings with
      their exact line ranges, then choose the smallest set of bulk-evidence
      blocks whose removal brings the root inside the bound. Prefer few large
      self-contained blocks: each member is a whole file to the shard packer.
      The per-hit adjudication map and the measured-range appendix under
      `## Attributable prompt size and repeated execution cost` are the obvious
      candidates; confirm that against the live headings rather than assuming.
      Do not cut a block containing a synthesis or conclusion — if a candidate
      mixes evidence and conclusion, leave the conclusion in the root and move
      only the enumeration. Record each cut as an exact `start,end` line range
      **in `MOVE_BASE`** before you edit, and put the ranges in your report.

- [ ] **Step 3 — perform the moves.** For each cut, in order: create the member,
      write its header paragraph, then append the block extracted from
      `MOVE_BASE` — not from the working tree. The only edit permitted inside a
      moved block is demoting or promoting its own heading markers so the
      member's top heading is `##`; every other byte is carried across
      unchanged. Replace the block in the root with its retained heading plus
      the pointer line.

- [ ] **Step 4 — update the references.** Rewrite every coverage row whose
      discharging heading moved, into the `<member path> § <heading>` form, and
      every in-document cross-reference that named a moved heading. Commit.

- [ ] **Step 5 — verify.** All four gates must pass before you report DONE.

      # G1 (V1) — the linked root still resolves at this commit
      git show "HEAD:$DOC" > /dev/null || echo "FAIL: root missing"

      # G2 (B-06) — every moved block is byte-identical to its baseline.
      # For each recorded range START,END and its member MEMBER:
      #   git show "$MOVE_BASE:$DOC" | sed -n "START,ENDp" > /tmp/base.block
      #   sed -n '/^## <first heading of the moved block>$/,$p' "$MEMBER" > /tmp/moved.block
      # Normalise ONLY the heading markers you changed in Step 3, then:
      #   cmp /tmp/base.block /tmp/moved.block || echo "FAIL: block drifted"
      # Write the exact commands you ran, and their output, into your report.

      # G3 — the retained root is the baseline minus exactly the moved ranges.
      # Reconstruct it: take git show "$MOVE_BASE:$DOC", delete the recorded
      # ranges, and diff that against the committed root. Every difference must
      # be a pointer line or a rewritten coverage/cross-reference cell, and you
      # must list them all. Any other difference is a failure.

      # G4 (V2) — every coverage row's fourth column resolves.
      # For each row: a bare value must match a heading in the root
      # character-for-character; a `<path> § <heading>` value must split on the
      # first ' § ', and the heading must match a heading in that member file
      # character-for-character. Report the row count checked and any failure.

      # G5 (V6) — packageability, after the commit
      OUT=$(mktemp -d)
      review-package .claude/plans/2026-09-02-issue-115-recovered-wayfind-findings.md \
        "$(git merge-base origin/main HEAD)" HEAD "$OUT/v6.json"
      # require exit 0 and budget_status within_budget, then: rm -rf "$OUT"
      # The destination is the FOURTH POSITIONAL argument. In diff mode
      # --output is rejected as an invalid invocation; that flag is detail
      # mode's. Always give it: the default destination is the range the final
      # review publishes to, and review-package publishes exclusively.

- [ ] **Step 6 — report.** Report `MOVE_BASE`, the before/after byte figures,
      each cut with its exact baseline range and resulting member, the G2 `cmp`
      commands and their output, the G3 difference list, the G4 row count, the
      G5 result, and anything you noticed but deliberately did not fix.

**Verification:** G1–G5 all pass. G2 proves byte-identity by comparison against
`MOVE_BASE`, not by reading; a task reporting DONE without G2's commands and
their output in the report has not met this gate.
