# Operation: `diff-review`

Read this when running `diff-review` — the correctness axis of the two-axis diff
review (the sdd skill defines the axes and owns dispatching the parallel native
conformance axis — that axis never comes through this skill). SKILL.md owns the
shared runtime contract: resolve policy, capability pre-flight, packet by paths,
exact ordered first lines `WORKTREE_ROOT: <absolute path>` then
`REVIEW_OPERATION: diff-review`, one foreground `codex:codex-reviewer` dispatch,
validation, one-time native `reviewer` fallback on a real Codex failure, never a
retry, concurrency never a fallback reason. The axis is never skipped. This
operation adds one pre-flight of its own — the size pre-flight below — which runs
after that capability check.

## Size pre-flight

SKILL.md's `command -v codex-companion` check is the capability pre-flight and runs
first; this size pre-flight runs after it, never before. A missing capability takes
the native flow and never dispatches, so measuring first would be wasted work, and
the native path is unscoped by construction. The separate capability fallback — this
skill or the bridge agent unavailable, so the controller dispatches the native
correctness reviewer itself — never reaches this pre-flight and is never scoped.

Measure the range in product terms before building the packet. Run it from the
worktree root (the helper is `~/.agents/bin/diff-scope`; use the full path if the
bare name does not resolve on PATH):

```
diff-scope <base-sha>..<head-sha> \
  --root <absolute worktree root> \
  --artifact-path <specDir> --artifact-path <planDir> \
  --format json
```

`<specDir>` and `<planDir>` are the caller's already-resolved bindings, passed
repository-relative. A dispatcher that has none passes the documented defaults
`.claude/specs` and `.claude/plans` rather than omitting the flags, so the run's own
spec and plan never consume review budget.

Read exactly three fields from the JSON:

- `product.changed_files` — the budget comparison, and `M` in every disclosure.
- `files[].path` — the subset, taken as the first 20 entries in the emitted order.
- `files[].changed_lines` — the per-file churn printed beside each path in item 7.

`product.changed_lines` and `excluded` are deliberately not read here: they are the
degradation gate's thresholds, not this pre-flight's, and must not be wired into the
scoping decision.

The budget is 20 product files and the comparison is strict — `changed_files > 20`
scopes the packet, `changed_files == 20` does not. A range measuring zero product
files is under budget and dispatches whole.

Take the subset from `files[]` verbatim: no filtering, no re-ranking. The helper
already ranks churn descending with a raw-path-bytes tie-break, a total order, so the
same range always yields the same 20 paths. Binary rows carry a churn of zero and
sort after every text row, so one enters the subset only once every text product file
is already in it.

**No measurement.** A helper that is absent, exits non-zero, emits output this
operation cannot parse, or selects a path this operation cannot represent in item 7's
listing (see *When the range is over budget*) yields no measurement — never a failure.
Dispatch exactly as an under-budget range does, six items and today's verdict format,
and report `unmeasured` to the calling controller. `diff-scope` reaches `~/.agents/bin` only
after a rebuild, so absence is a real state on a machine that has this skill.

An oversized diff is not a Codex failure and scoping adds no fourth failure class —
SKILL.md's closed list of three stands unchanged. Scoping never spends the one-time
native fallback and never triggers a retry. When Codex does fail on a scoped
dispatch, that one-time native fallback receives the same packet, item 7 and coverage
sentence intact.

The value this operation hands the calling controller is the **scope**, exactly one
of: `full` | `scoped: <N> of <M> product files` | `unmeasured`.

## Packet

**The `diff-review` packet replaces PLAN-REVIEW.md's packet wholesale** — it is
not that packet plus tweaks. It contains exactly:

1. The operation name, invocation directory, worktree root, current branch, and
   the base and head SHAs of the diff under review.
2. Scope line: review the diff `<base-sha>..<head-sha>` in the worktree for code
   correctness — bugs, boundary error handling, dead branches, assertions that
   fail to pin the documented contract, DRY against existing helpers, cross-task
   integration. Conformance to issue/spec/docs is the parallel axis's job;
   instruct the reviewer not to grade it.
3. The caller's correctness rubric by absolute path (sdd's
   `correctness-reviewer-prompt.md`), with concrete values supplied for every
   placeholder it names, including the review-package manifest and metrics.
4. The manifest root path and all four metrics (`root_bytes`, `total_bytes`,
   `file_count`, `largest_member_bytes`) from the caller's validated
   producer report, plus the plan path (routing context for what the tasks
   were). No shard list or diff contents ride in the packet.
5. Inferred verify commands and every applicable `AGENTS.md`/`CLAUDE.md`.
6. The standards layers matching the diff's file types
   (`~/.agents/standards/the-bar.md`, its `stacks/` shards, project
   `docs/standards/` shards whose globs intersect).

Nothing else rides along: no issue investigation, no spec, no domain docs, no
`codex.planReview.focus`, no `REVIEW-CONTRACT.md`. The light packet is what keeps
Codex inside its runtime budget; domain conformance belongs to the other axis.

### When the range is over budget

Under budget — or unmeasured — the packet is exactly the six items above. Over budget
it differs in exactly three places and nowhere else.

**Item 2 changes subject and gains a coverage sentence.** It becomes: review the
listed product files in the worktree, as changed across `<base-sha>..<head-sha>`, for
the same correctness subject matter, with the same instruction not to grade
conformance. Then, in substance:

> This is a scoped review: `<N>` of `<M>` changed product files, selected as the
> highest-churn files. Files outside the list are not under review in this pass — do
> not treat their absence from the list as evidence they are clean. Every finding you
> report must be anchored in a listed file. An unlisted file may be consulted and
> cited as evidence for such a finding; a defect lying wholly within an unlisted file
> is outside this pass and is not reported.

Scoping bounds what is supplied and what is graded, not what may be consulted. The
rubric's carve-out for inspecting code outside the diff to evaluate a concrete named
risk stands untouched — one focused check per named risk — so a cross-file finding
that reaches into an unlisted file is legal and reportable, as long as it is anchored
in a listed file. Silently grading an unlisted file, reporting a defect that lies
wholly inside one, or implying it was covered, is not.

**Item 4 changes the manifest's use, not its presence.** The scoped correctness
packet still carries the manifest root path and all four metrics as truthful
range-coverage evidence, but directs the reviewer: **do not read its shards**.
The full-range shards would defeat the 20-file evidence bound. Item 3 receives
all manifest/metric placeholders as usual and routes on the packet's explicit
scoped statement. Do not regenerate a smaller package: the conformance axis and
every unscoped reviewer validate that same manifest and read all shards once in
manifest order, explicitly reporting an unreadable or mismatched shard.

**Item 7 exists only when scoped**, and it is the reviewer's collection instruction,
not only a disclosure: the selected paths, worktree-root-relative, one per line, in
the helper's emitted order, each with its `files[].changed_lines` count. Direct the
reviewer to collect the diff for exactly those paths, one bounded read per listed
path (`git diff <base>..<head> -- ':(literal)<path>'`), and to treat that set as the
whole of the range under review. This is one invocation per selected path. An
unscoped packet has no item 7.

Spell that invocation protocol out in item 7 rather than leaving it to the reviewer:
**one invocation per path**, the path passed as a **single literal argument after
`--`**, never shell-joined with the other listed paths into one command line, and
pathspec magic disabled by the `:(literal)` prefix. `diff-scope` emits whatever bytes
Git records, so a selected path may carry a space, a newline, a non-UTF-8 byte, or a
leading `:`; treated as anything but one literal argument it splits or is
reinterpreted, and the reviewer silently reads a diff that is not the one this packet
bounded.

Item 7's listing is line-delimited, which carries every one of those byte classes
intact except one: a path whose bytes include a newline has no unambiguous one-per-line
form, and splitting the listing on newlines would hand the reviewer two paths that are
neither of them the selected file. That case does not scope. It takes the
no-measurement path above — dispatch the range whole, report `unmeasured` — rather than
list a path this packet cannot represent or quietly drop it from the subset. Dropping is
the outcome the bound exists to prevent: a silently shorter list still discloses `<N>`
of `<M>` and reads as covered.

The packet stays a paths packet either way: it never embeds per-file diffs.

## Reviewer output contract

First line is the axis verdict (`**Correctness:** Clean | Findings — 1–2
sentences`), then exactly three top-level sections `Critical` / `Important` /
`Minor` (must-fix-before-merge / should-fix / nice-to-have), ≤400 words total,
every finding with a stable ID, live `path:line` evidence, confidence (`high` /
`medium` / `low`), and unknowns (`none` when empty); `None.` under an empty
section; unreadable artifacts reported explicitly.

When the packet is scoped, the coverage opens that first line's assessment clause,
after the em dash — never between the verdict word and the dash:

```
**Correctness:** Clean — scoped to <N> of <M> product files; <1–2 sentence assessment>.
**Correctness:** Findings — scoped to <N> of <M> product files; <1–2 sentence assessment>.
```

`agent-evidence.py` `re.fullmatch`es this line, so the position is a contract rather
than a style: `**Correctness:** Clean (scoped: 20 of 44) — …` fails validation. A
scoped review may not use the bare `**Correctness:** Clean` form, because that form
has nowhere to put the coverage. An unscoped or unmeasured review keeps today's
format exactly, bare form included.

The coverage disclosure is mandatory on a scoped dispatch — state it in the packet as
a requirement, not a preference; a scoped result that omits it does not satisfy this
operation's output contract. Nothing downstream catches that omission:
`agent-evidence.py` fullmatches the shape of the first line and never sees whether
the packet was scoped, so a bare `**Correctness:** Clean` returned from a scoped
dispatch validates. The obligation lives in the packet and nowhere else.

## Disposition

Verify-and-disposition stays with the calling controller and its own fix-flow rules:
return the validated three-section result (or the fallback reviewer's) unmodified,
plus the reviewer identity (`Codex` | `Claude fallback` + failure class) and the scope
(`full` | `scoped: <N> of <M> product files` | `unmeasured`) for the caller's ledger.
That return is the single hand-off point — the controller records what it is given and
never re-derives the measurement.
