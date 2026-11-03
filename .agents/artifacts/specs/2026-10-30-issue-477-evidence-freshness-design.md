# Acceptance evidence stays fresh across commits outside the measured tree — issue 477

Issue: https://github.com/fagenorn/nix-config/issues/477. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "adds a deterministic freshness verb/helper and rewrites the sdd final-review freshness rule, an agent-workflow contract"}, "concurrency_or_persistence": {"value": "no", "evidence": "freshness reads git trees/diffs only; no locks or persisted state"}, "open_design_questions": {"value": "doubt", "evidence": "which module owns freshness and how the measured surface is named (tree identity minus record vs path set) are open"}, "criteria_shape": {"value": "no", "evidence": "four criteria, each verified by a named test or the declared suite"}}, "paths": ["python/agent_tools/verified_tree.py", "tests/test_verified_tree.py", "home/common/agent-skills/skills/sdd/final-review.md", "home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "python/README.md"]}`
Verdict: `{"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

sdd's final review grades each acceptance row that rests on a measurement taken at an
earlier commit: an `evidence` row, or a `code` row recorded `met` on a cited run outside
the Declared verification line. The rule for that grade is prose, applied by the LLM
controller and the conformance reviewer: the row goes `unverified` when a later commit
"touches that row's measured surface". Nothing defines the measured surface, so reviewers
treat any head move as stale. Committing the acceptance record itself, or merging the base
branch, therefore staled the `just build` evidence: #438's row was re-measured three
times (940c8664, 97dbbd34, 1b65c8e6) and #450's once more (8c799dfe), and both records
still ship that row `unverified`.

The owner wants a judgement on content, not on commits. A row measured at commit C stays
fresh while nothing it measured changes. A commit that changes only the acceptance record
leaves it fresh, and a change inside the measured content makes it stale.

## Solution

`verified-tree` already names "what a Git-backed build sees" as a tree identity. It gains
a third verb, `fresh`. The verb compares the tree of a given commit with the current
build-visible tree, ignores the acceptance record's own path, and prints `fresh` or
`stale` with the paths that differ. It is read-only and needs no project contract.

The sdd guidance stops describing the measured surface in prose. Its three freshness
sentences are replaced by this argv:

```
verified-tree fresh --since <Commit> --record <record path>
```

`stale`, or an exit 2, makes the row `unverified`. Those sentences are the acceptance-record
freshness check and Final verification step 4 in `final-review.md`, and the `evidence`
grading bullet in `conformance-reviewer-prompt.md`. Each replacement must be no longer
than the prose it removes, so the instruction-budget gate passes with no raise.

Demo, as the issue states it:

1. Commit build evidence at C, then commit only the acceptance record (C+1).
   `verified-tree fresh --since C --record <record>` prints `fresh`.
2. Then commit a change to a measured file. The same call prints `stale` and names that file.

## Decisions

### The `fresh` verb (per D1, D2, D3, D4)

- **Argv.** `verified-tree fresh --since <commit> --record <path>`. Both options are
  required, and the verb takes no positional argument.
- **`--since`** names a commit, given as a full or abbreviated SHA or any other revision
  that resolves to a commit. It is resolved with `git rev-parse --verify` to
  `<value>^{commit}`, and an option terminator comes first, so a value starting with `-` is
  never read as an option. A value that names no commit is an error. The output's `since`
  is the full commit SHA.
- **`--record`** is the acceptance record's path. A relative path is resolved against the
  current directory. After symlinks are resolved, the path must lie inside the worktree's
  top level, or the call is an error. The path need not exist. It becomes a
  repository-relative POSIX path, which is the one path removed from the comparison.
- **Comparison.** The left side is the tree of `--since`'s commit. The right side is
  `current_tree`, verified-tree's existing build-visible tree: the index with tracked
  working-tree edits applied, untracked files excluded. The verb lists the paths that differ
  with the same `git diff-tree -r --no-renames --name-only -z` form as `changed_paths`, so
  each side of a rename and every deletion counts. It then drops the record path. Nothing
  else is excluded. The tree diff gets one helper that `changed_paths` also uses, so there
  is one diff form.
- **Output.** Exit 0 prints one canonical JSON line, the same encoding as the other verbs:
  `{"changed": ["<path>", ...], "since": "<full commit sha>", "status": "fresh" | "stale", "tree": "<current tree>"}`.
  `changed` holds the differing paths in git's order. `status` is `fresh` exactly when
  `changed` is empty.
- **Errors.** These exit 2, with one `verified-tree: <message>` line on stderr and empty
  stdout: a revision that names no commit, a record path outside the worktree, a git
  failure, or a call made outside a git worktree. argparse usage errors also exit 2.
- **Footprint.** The verb never calls `resolve_project`, takes no lock, and changes no file (per D11).
  The real index, HEAD, the working tree, `verified-tree.json` and the persisted plan stay
  byte-identical.
- **Merges and reverts.** Freshness compares content, not ancestry, so neither gets a
  special case. A base-branch merge stays `fresh` only when it changes no measured path. A
  change that is later reverted to the measured content reads `fresh` again.
- **Write-ups.** A commit after C that changes only documentation, such as a spike report,
  reads `stale`, because the verb cannot prove that a check never reads a tracked file
  (per D8). The record's `Observed` column is the measurement's home. A separate write-up
  committed after the measurement means a re-measurement.

### Documentation of the verb

The module docstring is also `verified-tree --help`. It gains a paragraph for `fresh` that
states the argv, the output, the excluded path and the read-only footprint.
`python/README.md`'s `verified-tree` section gains one sentence naming the verb and what it
is for. That section is the command's one contract home, so no other document restates
the rule.

### sdd guidance (per D5, D6)

- **`final-review.md`, § Acceptance record.** The freshness paragraph becomes: before
  writing, run the argv for every `evidence` row recorded `met`, with that row's own
  `Commit`. Run it also for a `code` row recorded `met` on a cited run outside the Declared
  verification line, with that run's commit, unless the check was rerun and the fresh run
  cited. The paragraph keeps two clauses from the current text: only a commit later than
  a fixer's re-measurement counts, because the re-measurement writes a fresh `Commit`; and
  a row made `unverified` here is an acceptance finding that survives the fix wave.
- **`final-review.md`, § Final verification step 4.** The clause "whose measured surface
  the repair's commits touch" becomes "that the argv now reports `stale`".
- **`conformance-reviewer-prompt.md`, the `evidence` bullet.** "The commits after the
  measured commit leave the measured surface alone" becomes "the argv, with the row's
  `Commit` and the record beside the plan, prints `fresh`". A stale row stays `unverified`.
  The reviewer is read-only, and the verb is read-only too.
- **Bytes.** Each edited document ends no larger than it is at base 79cf7e3f, and
  `just agent-instruction-budget` passes with no ceiling raised.

## Test seams

- **The command, from source (AC1, AC2).** `tests/test_verified_tree.py` gains `fresh`
  cases. They use its existing harness: it drives `python -m agent_tools.verified_tree` in
  a throwaway fixture repository and asserts exit code, stdout JSON and stderr. They follow
  the module's existing `check` and `record` cases (agent-helpers rule 5). The cases (per D7):
  - A commit after C that changes only the record reads `fresh`, with `changed` empty
    (AC1; it fails today because no such verb exists).
  - A commit after C that changes a tracked measured file reads `stale`, with that path in
    `changed` (AC2).
  - An uncommitted tracked edit reads `stale`. An untracked new file reads `fresh`.
  - A change that is then reverted reads `fresh`.
  - A merge of a branch that changes a measured path reads `stale`.
  - An unknown `--since`, and a `--record` outside the worktree, each exit 2 with empty
    stdout.
  - The call leaves the record and the persisted plan files absent or byte-identical.
- **The guidance (AC3).** `home/common/agent-skills/tests/test_workflow_skill_contracts.py`'s
  `SDD_MACHINE_TEXT` pins the argv literal for both `final-review.md` and
  `conformance-reviewer-prompt.md`, like its existing `verified-tree check` pins (per D6).
- **The suite (AC4).** `just agent-workflow-tests` already lists `tests/test_verified_tree.py`.
  The plan also runs `just agent-instruction-budget` and the declared `just build` as gates.

## Out of scope

- Rewriting historical acceptance records, including #438's AC4 and #450's AC5. Point-in-time
  records keep their verdicts.
- ship-issue, CI and Nix changes. `fresh` is a verb of an existing command, so
  `lib/agent-tools.nix` gets no new row, and ship-issue grades no acceptance rows.
- Per-row measured-path declarations, a record-table parser, and any other exclusion
  beyond the record's own path (per D8). Narrowing the surface to a check's real inputs
  would be its own issue.
- Changing `check`/`record` semantics or the `verified-tree.json` schema.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Freshness is owned by a new `fresh` verb of the existing `verified-tree` command, in `agent_tools.verified_tree`, reusing `current_tree` and its error and exit conventions | Issue names the `verified-tree` tree identity; agent-helpers rules 1–2; the-bar *DRY* (one build-visible-tree definition) and *token economy* (no new tool) | A new `acceptance-freshness` module and command: a second tool, a new nix row and launcher, and a second caller of the same tree logic for one comparison |
| D2 | The measured surface is the build-visible tree (index plus tracked edits, untracked excluded) minus exactly the acceptance record's path, compared by content between the row's commit tree and the current tree | Issue: "judged against the content the evidence measured, e.g. the `verified-tree` tree identity"; the conservative reading keeps `stale` the safe default | Per-row path globs in a new record column: they change the record schema, and an LLM-authored glob that understates the surface yields a false `fresh`. Excluding all of `.agents/artifacts/`: tests read artifacts (e.g. replays), so a change there can change a check's result |
| D3 | CLI: `fresh --since <commit> --record <path>`, both required; exit 0 prints `{changed, since, status: fresh\|stale, tree}`; exit 2 for a revision that is not a commit, a record outside the worktree, or a git failure; no resolver, no lock, no writes | `check` already exits 0 with a status field; the-bar *fail loud*; the conformance reviewer is read-only | A verb that parses the whole markdown record and grades rows: a second parser of a schema that `final-review.md` owns, which would also take over verdict logic from the controller. A non-zero exit for `stale`: it diverges from `check`, which reports `unverified` with exit 0 |
| D4 | A base-branch merge, a rebase or a revert gets no special case: fresh exactly when the measured content is unchanged | Issue Q3: "do not over-promise"; content, not commits, is the issue's rule | Treating merges from the integration branch as fresh: the base's changes can change a build's outcome |
| D5 | The three prose freshness sentences in `final-review.md` and `conformance-reviewer-prompt.md` are replaced by the argv, ending net non-positive in bytes so `just agent-instruction-budget` passes unraised; that gate runs in the plan | Owner's hard constraint (the raise label is user-only); the-bar *DRY* (the command's contract lives in its docstring and `python/README.md`) | Adding an explanatory paragraph beside the existing prose: it needs a ceiling raise that the agent cannot apply, and it duplicates the contract |
| D6 | AC3 is measured by pinning the argv literal `verified-tree fresh --since <Commit> --record <record path>` in `SDD_MACHINE_TEXT` for both documents | agent-helpers rule 6: helper argv is machine-consumed, and no English phrase is pinned | Pinning a rule sentence: rule 6 forbids new English-phrase pins |
| D7 | AC1's and AC2's cases live in `tests/test_verified_tree.py`, the test module of the module that owns freshness | AC1 permits "or the module owning freshness"; the path it names, `home/common/agent-skills/tests/test_sdd_gate.py`, does not exist | Creating that file, or adding the cases to `tests/test_sdd_gate.py`: `sdd-gate` does not own freshness |
| D8 | A commit that changes only documentation or another tracked file outside the record still reads `stale`. This is a deliberate, conservative change from today's prose, where an LLM sometimes judged such commits harmless | the-bar *truthful terminal states*; nothing can deterministically tell which tracked files a check reads (a flake build copies the whole tree); the issue requires only the record-only and measured-file cases | An `--except` list chosen by the controller: an LLM-chosen exclusion brings back the judgement this issue removes, and it can produce a false `fresh` |
| D9 | `fresh` validates `--since`, then `--record`, then computes the tree. A `--since` that `git rev-parse --verify --end-of-options <since>^{commit}` rejects prints `--since <value> names no commit` in place of git's line; a `--record` that resolves outside, or to, the worktree's top level prints `--record <value> is not a path inside the worktree <top>` | The spec's error list and the-bar *fail loud*: one stderr line that names the bad option; `.` names no file, so excluding it would exclude nothing | Passing git's raw `fatal: Needed a single revision` through: it does not say which option was wrong. Accepting `.` as the record: a silent no-op exclusion |
| D10 | The conformance `evidence` bullet runs the argv without restating "with the row's `Commit`" (the `<Commit>` placeholder names that column) and folds its missing and stale cases into "a row missing or not `fresh` is `unverified`", which also covers an exit 2, so the document ends 12 bytes smaller | D5's byte constraint; the spec's rule that `stale` or an exit 2 makes the row `unverified` | Keeping the spec's longer wording with "the row's `Commit` and the record beside the plan": the document grows about 17 bytes, past its base size, which needs the user-only raise |
| D11 | `fresh` changes no file (index, worktree, `verified-tree.json`, the persisted plan); like `check`, building the current tree through `current_tree` may add Git objects. Amends D3's "no writes" | Phase-5 plan review PR477-01: `current_tree`'s `git add -u` and `write-tree` persist blobs and trees even under a temporary index; the module docstring already scopes `check`'s footprint to the index, HEAD and working-tree files | Isolating `fresh`'s objects in a temporary object directory: extra machinery for unreachable loose objects that `git gc` prunes, diverging from `check`'s tree computation that D1 reuses |
