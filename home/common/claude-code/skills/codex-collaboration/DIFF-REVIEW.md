# Operation: `diff-review`

The correctness axis of the two-axis diff review. Uses SKILL.md's retained `ResolvedProject` and validated direct-command result, `bindings.workflow.review.code`, and the `Critical`, `Important` and `Minor` headings; it never resolves, reads policy, infers a path or supplies a default. The sdd skill owns the parallel native conformance axis, which is never skipped.

## Contents

- Size pre-flight
- Packet, and its over-budget form
- Reviewer output contract
- Disposition

## Size pre-flight

Runs after the `capabilities.review.code` routing, never before: an unsupported capability dispatches no Codex call, so measuring first is wasted.

From the worktree root, measure the range (`~/.agents/bin/diff-scope` when the bare name does not resolve):

```
diff-scope <base-sha>..<head-sha> \
  --root <absolute worktree root> \
  --artifact-path <specification-directory> --artifact-path <plan-directory> \
  --format json
```

The spec and plan directories come from the caller's retained snapshot, with no fallback locations. Read exactly three fields:

- `product.changed_files`: the budget comparison, and `M` in every disclosure.
- `files[].path`: the subset, the first 20 entries in emitted order, taken verbatim with no filtering or re-ranking.
- `files[].changed_lines`: the churn printed beside each path in item 7.

Never wire `product.changed_lines` or `excluded` into this decision; they belong to the degradation gate.

The budget is 20 product files, compared strictly: `changed_files > 20` scopes the packet, `changed_files == 20` does not, and zero dispatches whole.

**No measurement**: an absent helper, a non-zero exit, unparseable output, or a selected path containing a newline (it has no unambiguous one-per-line form in item 7) yields no measurement, never a failure. Dispatch as an under-budget range, six items and today's verdict format, and report `unmeasured`. Never drop such a path from the subset instead.

Scoping is not a Codex failure and adds no failure class: it never spends the one native fallback or triggers a retry, and when Codex fails on a scoped dispatch the fallback gets the same packet, item 7 and coverage sentence intact.

The **scope** handed to the controller is exactly one of `full` | `scoped: <N> of <M> product files` | `unmeasured`.

## Packet

This operation's packet is its own, built from scratch. It contains exactly:

1. The operation name, invocation directory, worktree root, current branch, and the base and head SHAs.
2. The scope line: review the diff `<base-sha>..<head-sha>` in the worktree for code correctness (bugs, boundary error handling, dead branches, assertions that fail to pin the documented contract, DRY against existing helpers, cross-task integration), and do not grade conformance to the issue, spec or docs, which is the parallel axis's job.
3. The caller's correctness rubric by absolute path (sdd's `correctness-reviewer-prompt.md`), with concrete values for every placeholder it names, the review-package manifest and metrics included.
4. The manifest root path and its four metrics (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`) from the caller's validated producer report, plus the plan path as routing context. No shard list or diff contents.
5. Inferred verify commands, labelled as context on how the change is verified elsewhere, not a request to run anything (the runtime is read-only), plus every applicable `AGENTS.md`/`CLAUDE.md`.
6. The standards layers matching the diff's file types (`~/.agents/standards/the-bar.md`, its `stacks/` shards, the project's intersecting `docs/standards/` shards).

Nothing else rides along: no investigation, spec, domain docs, review-focus setting or `REVIEW-CONTRACT.md`. The light packet keeps Codex inside its runtime budget. It is a paths packet and never embeds per-file diffs.

### Over budget

An under-budget or unmeasured packet is exactly the six items above. A scoped one differs in exactly three places:

**Item 2** reviews the listed product files as changed across `<base-sha>..<head-sha>`, for the same subject and with the same conformance exclusion, and adds in substance:

> This is a scoped review: `<N>` of `<M>` changed product files, selected as the
> highest-churn files. Files outside the list are not under review in this pass — do
> not treat their absence from the list as evidence they are clean. Every finding you
> report must be anchored in a listed file. An unlisted file may be consulted and
> cited as evidence for such a finding; a defect lying wholly within an unlisted file
> is outside this pass and is not reported.

The rubric's carve-out for inspecting code outside the diff to evaluate a concrete named risk stands, one focused check per named risk.

**Item 4** keeps the manifest root and metrics as truthful range-coverage evidence but tells the reviewer **not to read its shards**, which would defeat the 20-file bound. Item 3 still gets every manifest placeholder and routes on the packet's scoped statement. Never regenerate a smaller package: the conformance axis and unscoped reviewers read that same manifest.

**Item 7** exists only when scoped: the selected paths, worktree-root-relative, one per line in the helper's order, each with its `files[].changed_lines`. It directs the reviewer to collect exactly those diffs and treat them as the whole range, spelling out the protocol: one invocation per path, `git diff <base>..<head> -- ':(literal)<path>'`, each path a single literal argument after `--`, never shell-joined with others, pathspec magic disabled by `:(literal)`.

## Reviewer output contract

The first line is the axis verdict, `**Correctness:** Clean | Findings — 1–2 sentences`, followed by exactly three sections `Critical` / `Important` / `Minor` (must-fix-before-merge / should-fix / nice-to-have), at most 400 words, each finding with a stable ID, live `path:line` evidence, confidence (`high` / `medium` / `low`) and unknowns (`none` when empty), `None.` under an empty section, and unreadable artifacts reported.

A scoped review puts the coverage at the start of the assessment, after the em dash:

```
**Correctness:** Clean — scoped to <N> of <M> product files; <1–2 sentence assessment>.
**Correctness:** Findings — scoped to <N> of <M> product files; <1–2 sentence assessment>.
```

`agent-evidence` `re.fullmatch`es this line, so `**Correctness:** Clean (scoped: 20 of 44) — …` fails, and a scoped review never uses the bare `**Correctness:** Clean`. An unscoped or unmeasured review keeps today's format, bare form included. State the disclosure in the packet as a requirement: nothing downstream knows the dispatch was scoped, so a bare verdict from a scoped dispatch would validate.

## Disposition

The calling controller keeps verify-and-disposition under its own fix-flow rules. Return the validated three-section result (or the fallback reviewer's) unmodified, with the reviewer identity (`Codex` | `Claude fallback` + failure class) and the scope (`full` | `scoped: <N> of <M> product files` | `unmeasured`). The controller records what it is given and never re-derives the measurement.
