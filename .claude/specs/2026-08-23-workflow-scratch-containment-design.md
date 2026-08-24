# Workflow scratch containment — design

Issue: [#102 — Stop leaking workflow scratch into the repository working tree](https://github.com/fagenorn/nix-config/issues/102)

## Problem

Two classes of ephemeral workflow scratch are written into a git working tree, and
the only thing keeping them out of a commit is a machine-local ignore file.

1. **Producer-report candidates.** `design`, `grill-with-docs`, `writing-plans` and
   `handoff` each prescribe writing their producer-report JSON to "a sibling
   temporary candidate JSON file". The artifact root is under `specDir`/`planDir`,
   so the sibling is inside the working tree. Every one of the four also says
   "remove the candidate on every outcome" — but says it as a fact, not as a
   mechanism, so nothing forces the failure and validation-rejection branches to
   run cleanup.

2. **Control-plane / run scratch.** `sdd-workspace` roots the SDD workspace at
   `git rev-parse --show-toplevel` — the *process cwd's* working tree. Invoked
   from an issue worktree it creates a nested `.superpowers/sdd/` ledger inside
   that worktree, which is exactly the substitution `from-issue` forbids for
   lifecycle state ("never substitute the current checkout or owner worktree").
   Two such nested ledgers exist right now, in `worktree-issue-104` and
   `worktree-issue-99-skill-prose-fixes`. The same class has a quieter member:
   `from-issue` and `orchestrate-issues` each tell the agent to write a
   `workflow-state` request file to "an absolute temporary path" without saying
   where, and an unlocated instruction resolves to the cwd — the issue worktree.

The backstop is genuinely absent. The tracked `.gitignore` holds only `result`,
`__pycache__/` and `*.pyc`. `.superpowers/` and `**/.claude/worktrees/` live in
`.git/info/exclude` — untracked, machine-local, invisible to every other clone.
The consequences are concrete: a fresh clone shows `.superpowers/` as untracked
and a broad `git add -A` commits it; and `worktrees/SKILL.md` requires
`git check-ignore -q .worktrees` to pass before it will create a worktree, which
in a fresh clone it does not, so that skill blocks.

## Solution

Give each class of scratch one correct home, make cleanup a named mechanism
rather than an assertion, and put a tracked ignore file behind both.

- **Report candidates leave the repository entirely.** All four producer skills
  write the report candidate to an OS-temp file created with
  `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` and remove it under an
  unconditional cleanup — a shell `trap` on `EXIT HUP INT TERM`, or the
  equivalent `finally`. The four contracts are stated with one verbatim shared
  clause so they cannot drift apart.

- **`handoff`'s publication sibling is untouched.** `handoff` uses the word
  "sibling" for two different things. The *publication temporary* must be a
  sibling of the durable destination, because publication is a hard-link or
  atomic replace and both require the same directory. That stays. Only the
  *report candidate* moves. The spec fixes the two names so the distinction is
  legible in prose and checkable by test.

- **The SDD workspace moves to the primary checkout, bucketed per checkout.**
  `sdd-workspace` resolves the primary checkout from git the way
  `review-package` already does, and returns
  `<primary>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`. The bucket
  preserves the per-worktree isolation the current cwd-rooted path got for free.
  `task-brief` and `review-package` both shell out to `sdd-workspace`, so this is
  a single-point fix.

- **Lifecycle request files get a stated home** — `${TMPDIR:-/tmp}` — closing the
  unlocated case of the same class.

- **A tracked `.gitignore` becomes the backstop**, covering `.superpowers/`, both
  worktree homes, and the candidate filename shapes.

- **Contract tests pin all of it**, including two tests that force a failure path
  and prove cleanup ran.

## Decisions

### The shared report-candidate clause

One clause, embedded verbatim in all four producer skills, each after its own
lead-in ending in `… to `:

> a report candidate outside every working tree — create it with `mktemp
> "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` template
> works on both macOS/BSD and Linux) — invoke `artifact-budget validate-report
> --boundary producer --input <report-candidate>`, and remove that candidate
> under an unconditional cleanup that runs on every outcome, including validation
> rejection and failure: a shell `trap` on `EXIT HUP INT TERM`, or the equivalent
> `finally`

The `${TMPDIR:-/tmp}` fallback and the explicit six-`X` template follow the two
idioms already in the corpus: `handoff`'s nondurable candidate and
`improve-codebase-architecture`'s temp-dir resolution. `review-package` already
implements the same shape in Python (`tempfile.NamedTemporaryFile` plus
`finally: unlink`).

Lead-ins, preserved per skill:

- `design`, `grill-with-docs` — "Only after the last artifact check, write the
  object as UTF-8 to …".
- `writing-plans` — "Write this object as UTF-8 to …".
- `handoff`, success path — "Only after the last artifact check, serialize the row
  as UTF-8 to …".
- `handoff`, failure re-emit — replaces "a new sibling report candidate" with
  "a fresh report candidate created and cleaned up the same way".

In `writing-plans` and `handoff` the clause today ends mid-sentence with the
return/hold instruction attached by a comma; that instruction becomes its own
sentence after the clause. Everything else in those Return-control sections is
unchanged: the state row, the metrics, the `notes` bound, the "return only the
exact validated stdout bytes" rule, and the exit-2-is-`failed` rule.

### Lifecycle request files get a home too

`from-issue` tells the owner to "write a new absolute temporary request file" for
every `direct-owner` call, and `orchestrate-issues` passes
`--request-file <absolute-json-path>` to `control`. Neither says *where*. An
unlocated instruction is the weaker version of a wrong one: the agent picks the
cwd, and the cwd is the issue worktree. `workflow-state` reads these files and
never retains them, so they are pure per-call scratch and belong in OS temp on
exactly the same terms as a report candidate.

Both prescriptions gain the same qualifier — a new absolute temporary request
file **beneath `${TMPDIR:-/tmp}`** — in `from-issue/SKILL.md` (two occurrences:
the first-call instruction and the re-call instruction) and in
`orchestrate-issues/SKILL.md`. Cleanup is not added: these files are consumed
within the call and carry no removal contract today, so tightening the location
is the whole of the change. This is a scope addition Phase 0 did not enumerate;
it is recorded rather than silently absorbed, and it is what makes the
contract test's "no skill prescribes a scratch path inside the working tree"
non-vacuous for this shape.

### The two `handoff` temporaries, named

`handoff` keeps a short clarifying sentence distinguishing them, because a later
reader fixing "the sibling problem" must not delete the load-bearing one:

- **publication temporary** — the checked artifact bytes, written as a sibling of
  the durable destination so the install is a same-directory hard-link or atomic
  replace. Sibling placement is a correctness requirement, not a convenience.
- **report candidate** — the producer-report JSON, which is never published, has
  no cross-call life, and therefore lives in OS temp.

### SDD workspace root resolution

`sdd-workspace PLAN_FILE` keeps its interface — one positional argument, prints
one absolute path, exits 2 with a message on stderr for every refusal. Its
resolution becomes:

1. `common = git rev-parse --path-format=absolute --git-common-dir`. Failure or
   empty output → exit 2.
2. `basename(common)` must be `.git`, else exit 2 ("invalid common Git
   directory").
3. `primary = dirname(common)`. `git -C "$primary" rev-parse --show-toplevel`
   must be `primary`, and `primary` must be a real directory that is not a
   symlink, else exit 2 ("invalid primary checkout").
4. `gitdir = git rev-parse --path-format=absolute --git-dir`, then the bucket:
   - `gitdir == common` → bucket `primary`;
   - `gitdir == "$common/worktrees/<name>"` where `<name>` is one non-empty path
     component that is neither `.` nor `..` → bucket `wt-<name>`;
   - anything else → exit 2 ("cannot resolve checkout identity").
5. `base = "$primary/.superpowers/sdd"`, `dir = "$base/<bucket>/<plan-basename>"`.
   Create `dir`; a creation failure exits 2 with a message naming `primary`, so a
   primary checkout outside the agent's writable area fails loudly instead of
   silently landing somewhere else. Write `*` to `"$base/.gitignore"`. Print
   `dir`.

The self-ignoring `.gitignore` write is kept even though this repository's tracked
`.gitignore` now makes it redundant here: these skills are global and run in
projects that have no such rule, and it is the only protection there.

Steps 1–3 are `review-package`'s `_primary_checkout` procedure, unchanged; it is
already proven live — delivery detail was published to the primary from an issue
worktree today. Step 4 is new.

`primary` is the same directory `from-issue` calls `ledger_repo_root` (documented
as "/absolute/primary-checkout"). `sdd-workspace` derives it structurally rather
than accepting it as an argument: `sdd` also runs with no lifecycle identity at
all, and the script exists to be the single source of truth for the workspace
location, which a second answer path would undermine.

The bucket is what keeps two checkouts executing the same plan basename apart.
Without it, a second attempt at the same plan on a new branch would read the
first attempt's `Task N: complete` lines and skip work that does not exist on its
branch — the ledger-misread failure `sdd-workspace`'s own header exists to
prevent, in its mirror-image form. `primary` and `wt-<name>` cannot collide: a
worktree bucket always carries the `wt-` prefix, so a worktree literally named
`primary` buckets to `wt-primary`.

The workspace still lives outside `.git/`, so the reason the current header gives
for its location — Claude Code denies agent writes to protected `.git/` paths,
which would block an implementer subagent's report file — continues to hold and
stays in the rewritten header alongside the new reason for the primary checkout.

### No migration of legacy nested workspaces

An in-flight `sdd` run whose ledger sits in a nested worktree workspace does not
get moved. `task-brief` re-resolves the workspace on every task, so a rebuild
that lands this change mid-run would leave the ledger at the old path and the new
briefs at the new one. The rollout rule is therefore operational, and belongs in
the plan's final task: **finish or abandon in-flight `sdd` runs before the
`just switch` that ships this change.** Auto-migration was rejected — it is
permanent code for a one-time condition, and the probe itself would have to read
the cwd's working tree, reintroducing the very resolution being removed.

### Residual removal

Nothing leaked remains in the primary checkout's working tree; its `.superpowers/`
holds only the three correct homes. The live residue is the two nested
`.superpowers/sdd/` ledgers inside other agents' *running* worktrees. Deleting a
live controller's ledger is the precise failure mode this design exists to
prevent, so the executing phase does not touch them. What it does:

- assert its own worktree contains no `.superpowers/` and no stray candidate;
- land the tracked ignore, which makes every one of those shapes non-committable
  from any clone;
- leave other worktrees alone — their nested ledgers are removed with the
  worktree at ship time.

The issue's "the eight currently leaked files are removed" is therefore satisfied
as a state criterion — no leaked candidate or scratch is committable, and none
remains in any working tree this branch owns — not as a literal file-count
deletion.

### `.superpowers/ship-review/` is a deliberate exception

`ship-issue`'s retained Minor/Discussion candidate is written to
`.superpowers/ship-review/<issue>/retained-detail.json` **in the feature
worktree**, and that is correct: on publication failure the flow re-reads it and
deliberately keeps the worktree, so the candidate's lifetime is meant to be the
worktree's lifetime. Phase 0 did not enumerate this path; it is recorded here
rather than silently absorbed. It stays where it is, gains a one-sentence
rationale in `ship-issue/REVIEW.md` so a future reader does not "fix" it, and is
the single named exception in the contract test's allowlist. The tracked ignore
covers it.

### The tracked ignore

`.gitignore` gains, under one comment explaining that these are ephemeral
agent-workflow scratch shapes whose real homes are the primary checkout's
`.superpowers/` and `$TMPDIR`:

```
.superpowers/
.worktrees/
**/.claude/worktrees/
*.tmp.??????
producer-report-*.json
review-package-report-*.json
```

`.superpowers/` and `.worktrees/` carry no internal slash, so they match at every
depth — including inside a linked worktree. `**/.claude/worktrees/` reproduces the
proven `.git/info/exclude` rule verbatim. `*.tmp.??????` matches the six-`X`
`mktemp` template `task-brief` uses for its atomic-replace sibling. The two
`*-report-*.json` patterns match the report-candidate prefixes prescribed here and
already used by `review-package`.

Verified against a scratch repository: every leaked shape tested is ignored and
`.claude/settings.json`, `.claude/specs/*.md`, `home/common/agent-skills/skills/**`
and a plausible `handoff-notes.md` are not. `handoff-*.md` was deliberately left
out — `handoff`'s durable destination is already inside `.superpowers/workflows/`
and its nondurable candidate is in `$TMPDIR`, so the pattern would only risk
masking a real document.

`.git/info/exclude` is left alone. It becomes redundant, not wrong, and it is
machine-local state this repository does not manage.

### Documentation

`CLAUDE.md` currently asserts that `sdd` task artifacts live "in the current
working tree". That becomes false, so the sentence is corrected in place: the
per-checkout bucket under the primary, the one deliberate worktree-local
exception, report candidates in `$TMPDIR`, and the tracked `.gitignore` as the
backstop that `.git/info/exclude` cannot be. That edit is made in the design
commit, not deferred to implementation, so the planner and implementer read the
target rather than the superseded claim; the plan verifies it rather than
repeating it. This repository has no `docs/` tree
and no ADR directory; none is created. No decision here clears the "hard to
reverse *and* surprising *and* a real trade-off" bar that would earn an ADR in a
repository that had one.

## Test seams

Four files, three of them existing. No new seam is invented and no test reaches
inside a script's internals.

1. **`home/common/agent-skills/tests/test_workflow_skill_contracts.py`** (existing)
   — the corpus-wide prose contract seam, plus the ignore backstop. Follows that
   module's prior art: `REPO_ROOT`-relative path constants, the
   `nested_workflow_documents()` corpus generator, and boundaries spelled exactly
   once at module level so two files cannot drift (`GATE_LINE_BOUNDARY`).
2. **`home/common/agent-skills/tests/test_sdd_workspace.py`** (new) — the
   `sdd-workspace` CLI, exercised end-to-end against a real `git init` primary and
   real `git worktree add` linked worktrees. Follows `test_task_brief.py`'s
   `make_repo` fixture style.
3. **`home/common/agent-skills/tests/test_review_package.py`** (existing) — the
   forced report-validation failure. Reuses the validator-stub mechanism that
   `test_unavailable_validator_has_one_stable_cli_failure` already establishes.
4. **`home/common/agent-skills/tests/test_task_brief.py`** (existing) — the forced
   copy failure, using the `PATH`-injected `bin/` the fixture already builds.

Only the new file is added to the `agent-workflow-tests` recipe in `justfile`.

### Assertions

Corpus scan covers `home/common/agent-skills/skills/**/*.md` and
`home/common/claude-code/skills/**/*.md`, plus `sdd/scripts/*` for the path
allowlist. All prose matching is done on whitespace-normalized text (`\s+` → one
space) on both sides, because the corpus hard-wraps at ~80 columns and every
contract sentence spans lines.

In `test_workflow_skill_contracts.py`:

- The shared report-candidate clause, spelled once as a module constant, appears
  in `design`, `grill-with-docs`, `writing-plans` and `handoff`.
- `handoff` contains the failure re-emit phrase "a fresh report candidate created
  and cleaned up the same way".
- No `*.md` under either skill root matches `sibling(?:\s+\S+){0,2}\s+candidate`.
  The failure message names the offending file. This is the regression pin for the
  four moved contracts; the bounded gap keeps it from firing on `handoff`'s
  legitimate "candidate … sibling temporary" sentences, where the words appear in
  the other order. Run against the corpus as it stands, this pattern matches
  exactly five spans — the five prescriptions being changed — and nothing else,
  so the test goes red before the fix and green after it with no other edits.
- `handoff` still contains its publication-sibling wording — the anti-regression
  pin that stops an over-eager future fix from moving the publication temporary
  out of the destination's directory.
- Every `\.superpowers/<segment>` occurrence across the corpus has `<segment>` in
  `{workflows, issue-delivery, sdd, ship-review}`. Those four are exactly the
  segments present today, so the allowlist is closed rather than aspirational and
  a new home cannot be introduced without touching this test.
- Both lifecycle request-file prescriptions name `${TMPDIR:-/tmp}`:
  `from-issue/SKILL.md` twice and `orchestrate-issues/SKILL.md` once.
- `sdd/SKILL.md` states the primary-checkout-rooted, bucketed path; neither a
  scanned `*.md` nor a file under `sdd/scripts/` contains
  `<repo-root>/.superpowers/sdd` — `task-brief`'s header comment carries that
  string today, so the scripts half of this assertion is load-bearing.
- `.superpowers/ship-review` appears in exactly one file, `ship-issue/REVIEW.md`,
  and that file carries the rationale sentence for the exception.
- `.gitignore` is tracked (`git ls-files --error-unmatch`) and contains every
  pattern above.
- **Isolated** ignore behaviour: build a throwaway `git init` repository in a
  temp dir, copy the repository's `.gitignore` into it, and run
  `git check-ignore -q --no-index` there for each leaked shape (must be ignored)
  and each keep shape (must not be). Running this against the repository itself
  would pass vacuously off `.git/info/exclude`; the isolation is the point of the
  test and must be stated in its docstring.

In `test_sdd_workspace.py`:

- From a linked worktree, the printed path is
  `<primary>/.superpowers/sdd/wt-<worktree-name>/<plan-basename>`, and
  `<worktree>/.superpowers` does not exist afterwards.
- From the primary checkout, the bucket is `primary`.
- Two linked worktrees running the same plan basename get two distinct
  directories: a `progress.md` written in one is absent from the other.
- `<primary>/.superpowers/sdd/.gitignore` contains exactly `*\n`.
- An unresolvable checkout identity exits 2 with the exact stderr message and
  creates no directory — driven by running the script with `GIT_DIR` pointed at a
  directory under the common dir that is not `<common>/worktrees/<name>`, with
  `GIT_COMMON_DIR` still the common dir. The assertion is on the exact message, so
  the test cannot pass by hitting some earlier refusal instead.
- A missing plan file still exits 2 (unchanged-behaviour pin).

In `test_review_package.py`:

- Report-validation failure removes the report candidate. The existing
  broken-validator stub cannot drive this: it fails at import, so `review-package`
  stops at "validator unavailable" long before a candidate exists. The stub this
  test needs is a shim `artifact_budget.py` on the fixture's `HOME`/`PYTHONPATH`
  that re-exports the real module's API when imported — so `check_artifact` and
  `load_limits` still work in-process — and exits non-zero when executed as a
  script with `validate-report`, which is exactly how `_validated_report` invokes
  it. Run diff generation under that shim with `TMPDIR` pointed at a fresh empty
  directory. Assert the failure is the report-validation failure and *not*
  "validator unavailable" (the non-vacuity check: the run reached the candidate),
  and that no `review-package-report-*.json` remains in that `TMPDIR`.

In `test_task_brief.py`:

- A failed member copy leaves no temporary sibling: put a `cp` stub on the
  fixture's `PATH` that touches a marker file and exits 1; `task-brief` exits
  non-zero, the marker exists (proving the branch was reached rather than an
  earlier refusal), and the output directory contains no `*.tmp.*` entry.

### Verification

`just agent-workflow-tests` for the Python suites, and `just build` for the Nix
evaluation, since every changed skill file is materialised through the flake.
`just build` is this repository's only local build gate; CI does not run the
Python suites.

### Files touched

Product files, in the order a plan would sensibly take them. Paths, not line
numbers — the paths are stable identities here, the line numbers are not.

| File | Change |
|------|--------|
| `home/common/agent-skills/skills/design/SKILL.md` | Return control: the shared clause (D1). |
| `home/common/agent-skills/skills/grill-with-docs/SKILL.md` | Return control: the shared clause (D1). |
| `home/common/agent-skills/skills/writing-plans/SKILL.md` | Return control: the shared clause (D1). |
| `home/common/agent-skills/skills/handoff/SKILL.md` | Report candidate → shared clause; failure re-emit reworded; the two-temporaries sentence (D1, D2). Publication protocol untouched. |
| `home/common/agent-skills/skills/from-issue/SKILL.md` | Two request-file prescriptions gain `${TMPDIR:-/tmp}` (D14). |
| `home/common/claude-code/skills/orchestrate-issues/SKILL.md` | The `control` request-file prescription gains `${TMPDIR:-/tmp}` (D14). |
| `home/common/agent-skills/skills/sdd/scripts/sdd-workspace` | Header rewrite plus the new resolution (D3, D4, D5). |
| `home/common/agent-skills/skills/sdd/scripts/task-brief` | Header comment: the default OUTFILE path shape. |
| `home/common/agent-skills/skills/sdd/SKILL.md` | Workspace bullet: new path shape and rationale; the `git clean -fdx` parenthetical now names the primary checkout, not the feature worktree. |
| `home/common/agent-skills/skills/ship-issue/REVIEW.md` | One rationale sentence pinning the deliberate exception (D7). |
| `.gitignore` | The six backstop patterns under one comment (D6). |
| `CLAUDE.md` | The `.superpowers/` homes sentence (D13). **Already applied in the design commit** — the plan must not re-edit it, only verify the shipped behaviour matches it. |
| `justfile` | Register `test_sdd_workspace.py` in `agent-workflow-tests`. |

Test files: the three existing suites named under Test seams, plus the new
`home/common/agent-skills/tests/test_sdd_workspace.py`.

## Out of scope

- **`workflow-state`'s ledger home** and **`review-package`'s delivery-detail
  home**. Both already resolve correctly — one from an explicitly supplied
  `--repo-root`, the other from the derived primary checkout — and neither is
  touched.
- **Moving `.superpowers/ship-review/`.** Its worktree-scoped lifetime is
  deliberate; see the decision above. It is documented and allowlisted, not
  relocated.
- **`artifact-budget` policy**, thresholds, and the producer-report schema. The
  report's *destination* changes; nothing about its content, validation, or budget
  does.
- **`patches/agent-plugins/`** — issue #104's territory, being edited concurrently.
- **`.git/info/exclude`** — machine-local, not repository state.
- **Migrating the two existing nested ledgers**, and any change to how or where
  `from-issue` / the harness creates worktrees.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Producer-report candidates move to `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"`, removed by an unconditional `trap`/`finally`, stated as one verbatim clause shared by `design`, `grill-with-docs`, `writing-plans` and `handoff`. | `handoff/SKILL.md` already uses that exact `mktemp` idiom for its nondurable candidate; `improve-codebase-architecture` establishes the `$TMPDIR`→`/tmp` fallback; `review-package._validated_report` already does the Python equivalent with `finally: unlink`. | Primary checkout `.superpowers/` — the candidate has no cross-call life, so durability buys nothing and it adds a second in-repo write path to police. |
| D2 | `handoff`'s **publication temporary** stays a sibling of the durable destination; only the **report candidate** moves. Both roles are named in the prose and pinned by test. | `handoff/SKILL.md`'s publication protocol installs by hard-link or atomic replace, which requires the same directory; the report candidate is never published. | Moving both to `$TMPDIR` — would break atomic publication across filesystems and silently turn a no-clobber install into a copy. |
| D3 | `sdd-workspace` roots the workspace at the **primary checkout**, resolved from git exactly as `review-package._primary_checkout` does, not at the process cwd's toplevel. | The issue author's follow-up comment (state root from `ledger_repo_root`, never the process cwd); `from-issue/SKILL.md` "Lifecycle identity"; `AUTO.md` documents `ledger_repo_root` as the absolute primary checkout; the sibling `.superpowers/` homes already live there. | OS temp — the SDD ledger is a resumable cross-session record whose loss makes controllers re-dispatch completed task sequences, and OS temp is swept between sessions. |
| D4 | No `--repo-root` flag and no caller-contract change; the primary checkout is derived structurally. | `sdd-workspace`'s header declares it the single source of truth for the workspace location; `sdd` also runs with no lifecycle identity, so there would be nothing to pass. | A required or optional `--repo-root`, mirroring `workflow-state` — creates a second answer to one question and a drift path between the three callers. |
| D5 | The workspace path gains a per-checkout bucket: `<primary>/.superpowers/sdd/{primary\|wt-<worktree-name>}/<plan-basename>/`; an unresolvable checkout identity exits 2. Amended in Phase 5 (narrowed, not reversed): the bucket keeps two checkouts running one plan from sharing a ledger, and no more than that. A bucket outlives the worktree that named it, so `ship-issue` prunes a feature worktree's bucket during worktree cleanup (D20); a stale read is narrowed, never made impossible. | The cwd-rooted path provided per-worktree isolation for free (`sdd-workspace` header, `task-brief`'s "per plan and per worktree"); moving to a shared root would let a second attempt at the same plan read the first attempt's completed-task lines and skip work absent from its branch. | Keying only on plan basename under the primary — smaller, but reintroduces exactly the stale-ledger misread the header exists to prevent. |
| D6 | Tracked `.gitignore` becomes the backstop with six patterns (`.superpowers/`, `.worktrees/`, `**/.claude/worktrees/`, `*.tmp.??????`, `producer-report-*.json`, `review-package-report-*.json`); `.git/info/exclude` is left in place but stops being load-bearing. | The issue's third acceptance criterion; `worktrees/SKILL.md` requires `git check-ignore -q .worktrees` to pass before creating a worktree, which fails in any fresh clone today. All six patterns and the keep-shapes were verified in a scratch repository. | Leaving the rules in `.git/info/exclude` — untracked, machine-local, invisible to every other clone, which is the defect being fixed. `handoff-*.md` was also rejected as too likely to mask a real document. |
| D7 | `.superpowers/ship-review/` stays in the feature worktree as the single named exception, documented in `ship-issue/REVIEW.md` and allowlisted in the contract test. Recorded as a scope addition Phase 0 did not enumerate. | `ship-issue/REVIEW.md` re-reads the retained candidate on publication failure and deliberately keeps the worktree, so its lifetime is the worktree's by design. | Relocating it to `$TMPDIR` or the primary — would decouple it from the worktree lifetime that the unpublished-detail stop depends on. |
| D8 | Residual removal is read as a state criterion. The executing phase asserts its own worktree is clean and lands the ignore; it does not delete the nested ledgers inside other agents' running worktrees, which disappear with their worktree. | Deleting a live controller's ledger is the exact stale/missing-ledger failure `sdd-workspace`'s header names; nothing leaked remains in the primary's working tree. | Sweeping every nested `.superpowers/` under `.claude/worktrees/` — would destroy issue #104's and #99's in-flight progress ledgers mid-run. |
| D9 | No migration of legacy nested workspaces; the rollout rule is "finish or abandon in-flight `sdd` runs before the `just switch` that ships this", carried as the plan's final task. | `task-brief` re-resolves the workspace per task, so a mid-run rebuild would split ledger and briefs across two paths. | Auto-migrating on first resolution — permanent code for a one-time condition, and its probe would have to read the cwd's working tree, reintroducing the removed resolution. |
| D10 | Contract tests are corpus-wide over both skill trees with a named `.superpowers/` segment allowlist, matched on whitespace-normalized text. | An enumerated file list cannot catch a newly added skill; the corpus hard-wraps at ~80 columns, so every contract sentence spans lines and unnormalized matching would silently never fire. | An enumerated four-file list — cheaper but blind to the next skill that copies the old wording. |
| D11 | The "forces the failure path" criterion is met at the two executable seams — `review-package`'s report validation and `task-brief`'s member copy — plus prose assertions that all four contracts name an unconditional cleanup mechanism. | Prose contracts cannot be executed; those two are the only code paths in scope that create and must clean a candidate. | Asserting cleanup only in prose — unfalsifiable, and it is the branch that demonstrably did not run. |
| D12 | The `git check-ignore` test builds a throwaway repository and copies `.gitignore` into it rather than querying this repository. | This repository's `.git/info/exclude` already ignores the same shapes, so an in-place check would pass even with an empty `.gitignore` — a vacuous pass of exactly the kind commit `34f9e69` closed elsewhere. | Running `git check-ignore` in the repository under test — simpler and worthless. |
| D13 | `CLAUDE.md`'s claim that `sdd` task artifacts live "in the current working tree" is corrected in place; no `docs/` tree or ADR directory is created. | `CLAUDE.md` is this project's only context doc and D3 falsifies that clause; the only `docs/areas/**` + `adr/` trees present are eval fixtures under `evals/fixture-repo/`. | Creating a `docs/` context map and an ADR for D3 — imposes a structure this repository has never had, on a decision that is cheap to reverse. |
| D14 | Lifecycle request files are pinned to `${TMPDIR:-/tmp}` in `from-issue` (twice) and `orchestrate-issues` (once); no cleanup contract is added. Recorded as a second scope addition Phase 0 did not enumerate. | Both skills say "absolute temporary request file" with no home, so the agent defaults to the cwd — the issue worktree — and the issue's first criterion covers control-plane scratch, not only report candidates. `workflow-state` consumes and never retains them. | Leaving them unlocated — the contract test would pass vacuously on a prescription that names no path at all, which is the weaker form of the same leak. |
| D15 | The `cannot resolve checkout identity` refusal is driven in test by a decoy bare repository at `<common>/decoy.git` with `GIT_DIR` pointed at it and `GIT_COMMON_DIR` still the common dir — correcting the driver named under Test seams. | Verified on git 2.51.2: a `GIT_DIR` under the common dir that is not itself a repository makes `git rev-parse` fail (`fatal: not a git repository`), so the script refuses at step 2 with `invalid common Git directory` and step 4 is never reached. The decoy keeps steps 1–3 passing (`--git-common-dir` → `<primary>/.git`, `git -C <primary> rev-parse --show-toplevel` → `<primary>`) and lands exactly on step 4. | Keeping the spec's driver — it asserts an exact message the run cannot produce, so the test either fails for the wrong reason or, with the message assertion relaxed, passes without exercising step 4 at all. |
| D16 | `test_review_package.py`'s validator shim registers itself in `sys.modules` before `exec_module` and refuses only when run as a script (`__name__ == "__main__"`). | Verified: without `sys.modules["_real_artifact_budget"] = _real`, `dataclasses` resolves `cls.__module__` through `sys.modules` and raises, `_bootstrap_validator` returns `False`, and the run stops at `review-package: validator unavailable` — precisely the vacuous pass the spec's non-vacuity assertion exists to exclude. | A shim that stubs only the CLI without re-exporting `check_artifact`/`load_limits` — both are used in-process before the candidate exists, so the run never reaches the cleanup branch under test. |
| D17 | The three lifecycle request-file prescriptions are rewritten to one identical literal, `a new absolute temporary request file beneath ${TMPDIR:-/tmp}`, so the contract assertion is an occurrence count (2 in `from-issue`, 1 in `orchestrate-issues`) plus a corpus rule: every `*.md` carrying `--request-file <absolute-json-path>` must also name `${TMPDIR:-/tmp}`. | The two `from-issue` sites differ today ("a new absolute temporary request file" vs "a new absolute request file"); D10 requires corpus-wide, drift-proof matching and D14 requires every site to name the home. | Appending the qualifier to each site's existing wording — three literals to keep in step and no corpus rule, which is the drift D10 exists to prevent. |
| D18 | A dictated test is measured against the dictated prose before it is written down. Task 1 gains an explicit re-anchoring step for the three live `assert_ordered` calls whose `candidate JSON`-before-`validate-report` anchors its own prose edit invalidates, both raw-text calls move onto `normalized(...)`, its sibling-candidate comprehension uses `finditer`, and it runs `just agent-workflow-tests` itself. | Measured: the four replaced blocks are exactly the ones carrying `candidate JSON` ahead of `validate-report`, so without the step the suite fails five assertions across three tests. Measured again on the post-edit text: raw `str.find` cannot see `report candidate outside every working tree` or `validate-report --boundary producer` because the ~80-column wrap splits both, which is precisely the condition D10 exists for. And `search` yields one span per file (four) where `finditer` yields five, making the step's stated offender count true. | Leaving the re-anchoring to Task 6 — it would put five known failures into five intervening commits and make Task 1's own "the whole suite still passes" claim false at the moment it is asserted. |
| D19 | `sdd-workspace` decides checkout identity **before** deriving the primary. A checkout whose git dir equals its common dir is the primary and resolves through `--show-toplevel`; only the linked-worktree branch applies the `basename == ".git"` check and the `dirname` derivation. | Measured on git 2.51.2: a submodule working tree reports `--git-common-dir` as `<super>/.git/modules/<name>` and a `git init --separate-git-dir=` checkout reports the bare git-dir path. Guard-first refuses both with `invalid common Git directory`, while the base-commit `git rev-parse --show-toplevel` handles both today — so guard-first would remove a globally installed skill from whole classes of repository. `test_sdd_workspace.py` gains a case for each shape; both fail against guard-first and pass against identity-first. | `git worktree list --porcelain` as the primitive — in a submodule and in a separate-git-dir repository its first `worktree` line reports the git directory, not the working tree. |
| D20 | `ship-issue/SKILL.md`'s post-merge cleanup removes the departing worktree's bucket at `<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/`, and only that one; `sdd-workspace`'s header stops claiming checkout-scoping removes the stale-ledger failure "structurally". | Under cwd-rooting the ledger died with the worktree; the bucket moves it to the primary, where nothing reclaims it — `sdd/SKILL.md` deletes a plan workspace only on the Clean terminal state. Worktree names are deterministic (`worktreePrefix` + issue number) and the ledger identity line is only `# SDD ledger — plan: <plan file path>`, so a same-day retry in a recreated worktree of the same name resolves to the same ledger and its resume rule honours the previous attempt's `Task <N>: complete` lines. | Leaving the prune unowned and keeping the "structurally" claim — the design would then assert a guarantee the mechanism does not provide, which is the failure class the header itself warns about. Also rejected: a sweep of `.superpowers/sdd/wt-*` at any other point, which would delete a live controller's bucket (D8). |
| D21 | Task 6's residue criterion becomes an executable gate — a `find` over this worktree for `producer-report-*.json`, `review-package-report-*.json` and `*.tmp.??????` with `.git` pruned, which must print nothing — and the step `rmdir`s the workspace its own `sdd-workspace` call created, guarded so a non-empty directory survives and a refusal cannot fail the step. | The plan root promised a residue-free assertion the member never implemented, leaving the issue's fourth acceptance criterion with no executable form. The three shapes are exactly what this plan's own machinery emits and what D6's patterns ignore (Task 1's `mktemp` template, `review-package`'s `NamedTemporaryFile` prefix, `task-brief:96`'s `mktemp "${out}.tmp.XXXXXX"`). Both the gate and the `rmdir` pair were run in a scratch repository and against this worktree before being written down. | Keeping the prose promise without a command; and letting the gate leave its own workspace behind, which would have a scratch-containment verification step depositing scratch. |
| D22 | The `sdd-workspace` header's self-ignore rationale reads "a project whose own `.gitignore` already covers these shapes gets it twice over, and a project whose `.gitignore` does not gets it only from here." | The dictated text said "a project whose does not gets it at all" — a noun-less clause that also states the opposite of the intent. The self-ignoring file is the *only* protection in a project with no rule of its own, exactly as this spec's own self-ignore paragraph and the plan's Global Constraints already say. | Deleting the clause — it is the one sentence explaining why the redundant-here write is kept, which is the question a future reader will ask. |
| D23 | Two adjacent prose-truth corrections ride along: `handoff`'s new paragraph scopes its count to the durable publication route and retires the third (nondurable) temporary in a closing sentence, reusing the file's existing "sibling temporary" rather than coining a name; and `worktrees/SKILL.md:14` stops attributing ledgers and review packages to the feature worktree. | `handoff/SKILL.md:9-14` already creates a nondurable `mktemp "${TMPDIR:-/tmp}/handoff-XXXXXX.md"` candidate, so "two different temporaries appear below" was wrong on its face, and the publication protocol at lines 76-91 still says "sibling temporary" — a new coinage would have needed a matching rename there. After D3 the `sdd` ledger and its review packages live in the primary checkout; only `ship-issue`'s retained detail (D7) is worktree-local. | Coining "publication temporary" in the corpus and renaming the protocol to match — a wider edit to a section D2 says not to touch. Leaving `worktrees/SKILL.md` alone — it would keep naming the wrong files for the wrong checkout in the skill whose whole job is worktree safety. |
| D24 | Task 5 moves from the `low-risk` lane to `full`, and its lane justification prose is replaced. | An ignore pattern is repo-wide and silent: an over-broad rule hides real files from every future `git add -A` in every clone, and neither `just build` nor the Nix evaluation would notice. Lane follows the cost of a wrong answer, not the size of the diff. | Keeping `low-risk` on the grounds that the change is one file and locally verifiable in one command — true of the diff, false of the blast radius. |
| D25 | The pre-existing issue-102 worktree is **resumed**, by `git worktree move` onto the lifecycle envelope's path `.claude/worktrees/worktree-issue-102-workflow-scratch-containment`, rather than deleted or left beside a second fresh worktree. | `from-issue/SKILL.md` Phase 0 makes a matching worktree deletable only when *provably disposable*; this one carried commit `503f7dc`, the spec and plan artifacts, and a pushed branch, so three of the four resume signals were present. Direct-autonomous acquisition can only reserve an **absent** candidate path, so the ledger's envelope path and the existing checkout had to be reconciled by moving the checkout onto the envelope path — the one operation that preserves every commit and leaves the branch identity untouched. The move also makes the directory's final component equal the branch name, which `AUTO.md`'s delegated-owner branch check requires. The move renames the checkout, so two path facts in the plan package move with it: the Global Constraints verification root, and Task 6 Step 6's expected `wt-<worktree-name>` bucket. | Creating a second worktree from `origin/main` at the envelope path — the branch name would have collided, and the prior owner's committed work would have been stranded. Also rejected: `git worktree remove` + `git branch -D`, which Phase 0 forbids on anything not provably disposable. |
| D26 | The seeded `sdd` ledger records Tasks 1-3 as `implemented` with an explicit "first-pass full-lane review NOT run" line, **not** as `Task <N>: complete`. | The three tasks landed in one commit made outside the `sdd` loop, so no per-task review ever ran; writing `complete` would assert a review that did not happen, and `sdd` treats a `complete` line as final. The `implemented`-then-`review dispatched` shape has prior art in this repository's own issue-99 ledger, written by an attempt-2 controller after the previous owner died before review. | Writing `Task <N>: complete` to skip straight to Task 4 — cheaper, but it would launder three unreviewed full-lane tasks past the gate the lane exists for. Also rejected: leaving the ledger absent, which sends `sdd` to re-implement work already at HEAD. |
| D27 | The Phase-5 standards review is **not** re-run on resume; its recorded provenance and dispositions continue to govern. | The reviewed plan's tasks, constraints, test seams and lane assignments are byte-identical to what the review passed; this attempt's only plan edit is an additive `## Execution state` section that describes where execution stands, not what is to be built. | Re-running the full standards review — it would re-derive an unchanged verdict at the cost of an entire reviewer pass. Also rejected: editing task content on resume, which would genuinely invalidate the review and require one. |
| D28 | The Terminal return procedure's `--result-file` relocation to `${TMPDIR:-/tmp}` plus its unconditional-cleanup contract — implemented in `503f7dc` beyond what Task 2 asked for — is **accepted and kept**, not reverted, and is recorded here with the same standing D14 gave the request-file change. | The result file is the same class of ephemeral scratch as the request file: a temporary JSON the owner writes, hands to `workflow-state finish`, and never reads again. D14 scoped Task 2 to the request file as a *scoping* judgment, not a correctness one, and reverting would leave the terminal result file as the single uncontained scratch shape in a change whose whole subject is scratch containment. The addition ships with its own pins (`RESULT_FILE_HOME`, `RESULT_FILE_INVOCATION`, two tests) and the cleanup cannot race the consumer, which reads the file within the call. | Reverting the hunk and its constants/tests to hold Task 2 to D14's letter — restores scope discipline at the cost of shipping an incoherent containment story, and the revert is itself an unreviewed late edit. Also rejected: silently keeping it unlogged, which is what made it a review finding in the first place. |
| D29 | Task 5's rationale that this repository's `.git/info/exclude` "already ignores the same shapes" is **stale**; the file is the pristine git default and ignores nothing. The task's dictated `.gitignore` bytes and both of its tests are kept exactly as written. | Measured on the live primary checkout: `.git/info/exclude` holds only git's default comment block, and `git status` reports `.claude/worktrees/` as untracked. Nothing dictated by the task depends on the premise — the isolated-repository test (D12) is if anything *more* clearly non-vacuous without it, and the shipped `.gitignore` comment claims only that `.git/info/exclude` is machine-local, which is true regardless. | Rewriting Task 5's rationale prose mid-execution — it would change a reviewed plan member to correct a sentence no artifact depends on. Also rejected: switching the test to an in-place `git check-ignore` now that the premise is false, which would couple the test to one machine's state. |
| D30 | This attempt keeps the seeded `sdd` ledger in the primary bucket `<primary>/.superpowers/sdd/wt-worktree-issue-102-workflow-scratch-containment/` while the *installed* `sdd` toolchain — the Nix-materialised pre-Task-3 build — writes briefs and review packages into the worktree-local `.superpowers/sdd/<plan-basename>/`. A pointer file in the worktree-local directory names the real ledger. | Task 3's resolver is committed on this branch but not yet materialised through the flake, so `task-brief` and `review-package` still resolve the old path; the ledger, however, already holds this run's seeded state (D26) and moving it would risk the exact stale-ledger failure the bucket exists to prevent. Task 6 Step 6 already tolerates both: its residue gate names only candidate and temporary shapes, and it explicitly leaves this run's own pre-Task-3 `.superpowers/` alone. | Migrating the ledger into the worktree-local workspace to match the installed tools — it would move the run's only durable record to the checkout that disappears at ship time. Also rejected: running the branch's own uninstalled scripts as the orchestration toolchain, which would execute unreviewed code as infrastructure for its own review. |
| D31 | Task 4's dictated `ship-issue/SKILL.md` prune paragraph is **corrected during execution**: the bucket path is captured from the worktree's own git directory into `$BUCKET` before `git worktree remove` runs, and the prose directs the reader at that recorded value while keeping the `wt-<worktree-name>` shape as description. | The dictated wording named `<worktree-name>`, a component the step never defines and that `git worktree remove` + `git worktree prune` destroy before the paragraph executes, leaving `basename <worktree-path>` as the only available guess. `sdd-workspace` derives the bucket from the git *registration* name, which diverges from the basename in exactly the collision case the paragraph exists to handle — a stale registration makes `git worktree add` register `<name>1`, so the guess names another worktree's bucket, the deletion D8 and the paragraph's own closing sentence both forbid. The plan's Global Constraints require dictated prose to describe behaviour that is true after its task; this block did not meet that bar, which is what authorises the correction. | Shipping the dictated wording unchanged and treating the gap as a documentation nit — it is a destructive instruction with a live-ledger blast radius. Also rejected: weakening `test_ship_issue_prunes_the_removed_worktrees_sdd_bucket` to accommodate new prose; the literal stayed pinned and the test was tightened to also pin the scope sentence. |
| D32 | `from-issue`'s Phase-0 orphan cleanup — the second documented flow that removes a feature worktree — is left **without** a bucket prune, and the gap is recorded as an accepted residual rather than closed by widening Task 4 beyond its file list. | The dangerous case is a surviving bucket whose ledger carries `Task <N>: complete` lines, which requires a plan to have been executed in that worktree. Phase 0 deletes only a *provably disposable* worktree: zero commits ahead, no active or handed-off ledger attempt, **no spec/plan artifacts under `specDir`/`planDir` inside it**, and no uncommitted work. A worktree that ran a plan fails that test — committed artifacts make it non-zero-commits-ahead, uncommitted ones route to the stop-and-ask branch — so the orphan-cleanup path cannot reach the state the prune protects against. Task 3 moving the ledger to the primary does not weaken the check, which looks for the artifacts, not the ledger. | Adding a prune clause to `from-issue/SKILL.md` — it is Task 2's file and Task 2 is closed, so this would be an unplanned late edit to a reviewed skill for a case the disposability test already blocks. Also rejected: leaving the asymmetry unrecorded, since the plan's own invariant calls `ship-issue` "the one flow that removes a feature worktree" and the corpus names two. |
