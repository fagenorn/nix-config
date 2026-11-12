# Operation: `diff-review`

The correctness review of a delivery range; the calling controller runs its own reviewers in parallel. Uses SKILL.md's retained `ResolvedProject` and validated direct-command result, `bindings.workflow.review.code`, and the `Critical`, `Important` and `Minor` headings; it never resolves, reads policy, infers a path or supplies a default.

## Contents

- Caller input
- Size pre-flight
- Packet, and its over-budget form
- Reviewer output contract
- Disposition

## Caller input

A diff range (`<left>...<right>` or `<left>..<right>`) and the worktree, and when the caller gives them, the plan path (routing context only) and the acceptance criteria. In the worktree, resolve `<head-sha>` with `git rev-parse <right>` and `<base-sha>` with `git merge-base <left> <right>` for a three-dot range or `git rev-parse <left>` for a two-dot one; an unresolvable range stops before packet construction.

Further ranges the caller names as `git -C <worktree> diff <base>...<branch>` (a plan's declared branches) are each resolved in their own worktree the same way and reviewed with the delivery range, each with its own size pre-flight and slices.

## Size pre-flight

Runs after the `capabilities.review.code` routing, never before: an unsupported capability dispatches no Codex call.

From the worktree root, measure the range (`~/.agents/bin/diff-scope` when the bare name does not resolve):

```
diff-scope <base-sha>..<head-sha> \
  --root <absolute worktree root> \
  --artifact-path <specification-directory> --artifact-path <plan-directory> \
  --format json
```

The spec and plan directories come from the retained `bindings.paths.artifacts`, with no fallback locations. Read exactly three fields:

- `product.changed_files`: the budget comparison, and `M` in every disclosure.
- `files[].path`: consecutive slices of 20 entries in emitted order, taken verbatim with no filtering or re-ranking.
- `files[].changed_lines`: the churn printed beside each path in item 6.

Never wire `product.changed_lines` or `excluded` into this decision; they belong to the degradation gate.

The budget is 20 product files, compared strictly: `changed_files > 20` gives each slice its own scoped dispatch, so every product file is reviewed once; `changed_files == 20` does not, and zero dispatches whole.

**No measurement**: an absent helper, a non-zero exit, unparseable output, or a selected path containing a newline (it has no unambiguous one-per-line form in item 6) yields no measurement, never a failure. Dispatch as an under-budget range and report `unmeasured`. Never drop such a path from a slice instead.

Scoping adds no failure class; the scope reaches the controller only inside `raw_summary` (see `## Disposition`).

## Packet

This operation's packet is built from scratch and contains exactly:

1. The operation name, invocation directory, worktree root, current branch, and the base and head SHAs.
2. The scope: review the diff `<base-sha>..<head-sha>` in the worktree for code correctness (bugs, boundary error handling, dead branches, assertions that fail to pin the documented contract, DRY against existing helpers, cross-task integration), and any acceptance criterion the caller passed that the diff leaves unmet.
3. The caller's acceptance criteria and plan path, labelled routing context.
4. Inferred verify commands, labelled as context on how the change is verified elsewhere, not a request to run anything (the runtime is read-only), plus every applicable `AGENTS.md`/`CLAUDE.md`.
5. The standards layers matching the diff's file types (`~/.agents/standards/the-bar.md`, its `stacks/` shards, the project's intersecting `docs/standards/` shards).

It is a paths packet and never embeds per-file diffs.

### Over budget

An under-budget or unmeasured packet is exactly the five items above. A scoped one changes item 2 and adds item 6.

**Item 2** reviews the listed product files as changed across `<base-sha>..<head-sha>`, for the same subject, and adds in substance:

> This is a scoped review: `<N>` of `<M>` changed product files, one slice of the
> range. Files outside the list are not under review in this pass — do
> not treat their absence from the list as evidence they are clean. Every finding you
> report must be anchored in a listed file. An unlisted file may be consulted and
> cited as evidence for such a finding; a defect lying wholly within an unlisted file
> is outside this pass and is not reported.

**Item 6** exists only when scoped: the selected paths, worktree-root-relative, one per line in the helper's order, each with its `files[].changed_lines`. It directs the reviewer to collect exactly those diffs and treat them as the whole range, spelling out the protocol: one invocation per path, `git diff <base>..<head> -- ':(literal)<path>'`, each path a single literal argument after `--`, never shell-joined with others, pathspec magic disabled by `:(literal)`.

## Reviewer output contract

Exactly three sections `Critical` / `Important` / `Minor` (must-fix-before-merge / should-fix / nice-to-have), at most 400 words, each finding with a stable ID, live `path:line` evidence, confidence (`high` / `medium` / `low`) and unknowns (`none` when empty), `None.` under an empty section, and unreadable artifacts reported. A scoped review starts with `scoped to <N> of <M> product files`; state that in the packet as a requirement.

## Disposition

Map each validated slice result with reviewer identity `Codex`: `Critical` findings as `critical`, `Important` as `important`, `Minor` as `minor`. Return exactly one object to the calling controller by this rule (an unsliced or unmeasured review is one slice):

1. All slices run together, as background jobs of one shell command that waits for them all (retries likewise); slice order is the delivery range's, then each further range's.
2. `findings` is every completed slice's mapped findings concatenated in slice order, each unmodified.
3. `verdict` is `pass` only when every slice ran and none reported a `Critical` or `Important` finding; otherwise `findings` (`Minor` findings alone never make it `findings`).
4. `available` is `false` when any slice fails its retry (capacity, runtime, payload or schema): the completed slices' findings stay in `findings`.
5. `raw_summary` is the scope disclosure: the scope line, exactly one of `scope: full`, `scope: unmeasured` or `scope: <K> slices over <M> product files`; then `base <base-sha> head <head-sha>`; then, for a sliced review only, one line per dispatched slice `slice <i>: scoped to <N> of <M> product files; <assessment>` in slice order, a failed slice's line giving its failure class and verbatim message, then `failed slices: <i>[, <j>]` when any failed. Each further range adds a block after it, opened by `range <worktree> <base>...<branch>` and followed by its own such lines.

The raw transcript stays out of the repository, plan, issue, PR and commits.
