# Issue 255 — an isolated Git record view for CORE

## Problem

CORE's review records are meant to be a function of two pinned trees and one
record policy. They are not. The Git process that renders them still reads the
repository's `info/attributes`, the user's attributes file, a checked-out
`.gitattributes`, `diff.orderFile` and a handful of other settings from every
configuration scope and from the environment. The same pinned commits
therefore render different records on differently configured hosts. Retained
derivation then publishes a different `issue-121.json` and a different anchor,
and nothing refuses. The
[REPLAY design](2026-10-04-issue-249-retained-derivation-replay-design.md)
recorded this as RP24 and narrowed its determinism claim to its own code. The
[EVIDENCE design](2026-10-05-issue-235-retained-review-evidence-design.md)
worked around it with a host check before each publication (EV5).

This child fixes the root cause in CORE's Git layer. Afterwards a review record,
a commit subject and the issue-100 recipe output depend only on the objects,
the policy and the Git version. The guarantee holds whatever host or repository
renders them.

## Binding designs

The [CORE design](2026-09-30-issue-233-review-projection-core-design.md) covers
the record policy, the packing-policy digest, the history authority and its
existing defences. The REPLAY design binds through RP8, RP11 and RP24, and the
EVIDENCE design through its trust pin and its full-shape reproduction case. This
spec does not restate them.

## Measured behaviour (Git 2.51.2)

Probes in a disposable repository under `$TMPDIR` each rendered every record
view: `--numstat -z`, `--name-only -z`, `--name-status -z`, and `--binary -U<n>`
for `n` in 10 and 0. They used today's `RECORD_POLICY` and changed exactly one
setting at a time.

**Changes records today:**

- an `info/attributes` rule `-diff`, `binary`, or `diff=<driver>` where the
  driver sets `binary = true`
- `core.attributesFile` at any scope
- the default user attributes file, under `$XDG_CONFIG_HOME/git/attributes` or
  `$HOME/.config/git/attributes`
- a working-tree `.gitattributes`. An index-only copy is not read for a
  tree-to-tree diff.
- `GIT_ATTR_SOURCE`, and `attr.tree`
- `diff.orderFile` set in the repository, global or command-line scope
  (`GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`)
- `diff.suppressBlankEmpty`
- `core.bigFileThreshold`, which changes the numstat view only
- `GIT_DIFF_OPTS`, which overrides the explicit `-U<n>`
- `i18n.logOutputEncoding` for subjects. `UTF-7` re-encodes `é` into
  different bytes that are still valid UTF-8, so nothing refuses.

**Already neutral under the policy's explicit arguments:**

- `diff.algorithm`, `diff.renames`, `diff.renameLimit`, `diff.context` and
  `diff.interHunkContext`
- `diff.indentHeuristic`, `diff.noprefix`, `diff.mnemonicPrefix`,
  `diff.srcPrefix`, `diff.dstPrefix` and `diff.relative`
- `diff.external` and `GIT_EXTERNAL_DIFF`, and `textconv` drivers
- `color.*`, `diff.colorMoved` and `diff.wsErrorHighlight`
- `core.abbrev`, `diff.ignoreSubmodules`, `diff.submodule` and `core.quotePath`
- `diff.wordRegex`, `diff.statNameWidth`, `diff.dirstat`, `core.whitespace`,
  `core.autocrlf` and `core.eol`

**Neither override nor refusal is clean:**

- A command-line `-c` overrides every configuration scope, the environment
  scopes included.
- Nothing overrides the repository's `info/attributes` except not using that
  Git directory.
- Refusing is unsafe here. `review_task7.compose` turns any `GenerationError`
  into `EstimateError("unsupported_composition")`, and issue 121 publishes that
  as an outcome row. A refusal raised while a record is rendered can therefore
  become different published bytes.

**Probed and found insensitive:** the projection's reconstruction step,
`git apply --cached --binary --whitespace=nowarn` in its scratch index. Changing
`apply.whitespace`, `apply.ignoreWhitespace`, `core.whitespace`, the
end-of-line settings, user attributes, or a template that injects
`info/attributes` and configuration did not change its result.

**Measured:** a fresh bare *view* Git directory with an absolute alternate to
the source object directory, run under the scrubbed environment below,
rendered byte-identical output to a clean source repository. That held for all
five views, with every hostile source above active at once, and from a linked
worktree. A call costs about 24 ms, including object-directory discovery,
against about 10 ms today.

## Solution

CORE gains one isolated Git runner, `record_git(repo, *args) -> bytes`, in
`agent_tools.review_actual`. Every Git invocation whose output becomes a record
or a recorded field runs through it (D1, D4). For each call it:

1. **Discovers** the source's absolute object directory and object format with
   one `rev-parse --path-format=absolute --git-path objects
   --show-object-format`. This runs in the caller's environment, as `_run_git`
   does today. The history authority's routing refusal still guards these
   commands, as before.
2. **Builds a view** in a private temporary directory, without running
   `git init`, so no template applies. The view contains:
   - `HEAD`, pointing at an unborn branch
   - an empty `refs/`
   - `config`, which declares only `core.repositoryformatversion` and
     `core.bare = true`, plus `extensions.objectFormat` for a SHA-256 source
   - `objects/info/alternates`, naming the discovered absolute object
     directory. Git follows the source's own alternates from there.
3. **Runs** `git --git-dir=<view> <args>` with the view directory as its
   working directory, under the record environment. That environment is the
   caller's environment minus every `GIT_*` variable and `XDG_CONFIG_HOME`,
   plus these settings:
   - `HOME=<view>`, which holds no global configuration and no default
     attributes file
   - `GIT_CONFIG_NOSYSTEM=1`
   - `GIT_ATTR_NOSYSTEM=1`

   A separate `GIT_CONFIG_GLOBAL` would only duplicate `HOME=<view>`, so the
   runner does not set one (D7).
4. **Removes** the view on every outcome. It maps `OSError` and a non-zero exit
   to `GenerationError("git command failed")`, the same error and message
   `_run_git` uses today.

No view is cached between calls. This matches the history authority's "no
retained cache" rule.

The view has no working tree, no index, no committed `HEAD`, no
`info/attributes`, no configuration of its own beyond format, and no reachable
user, global, system or environment configuration. No attribute source exists
anywhere, and the only configuration left is Git's built-in defaults plus the
policy's own `-c` arguments. The argv is unchanged, so `RECORD_POLICY` and its
digest stay byte-for-byte the same, and so do `PACKING_POLICY_SHA256` and every
retained payload domain (D2).

**Callers:**

- **`git_diff`** runs its unchanged argv through `record_git`.
- **`commit_subject(repo, sha)`** is a new function in `review_actual` that
  replaces both copies of `show -s --format=%s`: the one in `_commits` and the
  one in the projection's reconstruction. It runs through `record_git` and keeps
  today's strict UTF-8 decoding.
- **`review_issue100`'s recipe runner** runs its pinned recipe argv through
  `record_git`. It maps `GenerationError` to `Issue100Error("evidence_unavailable")`,
  the same code its `CalledProcessError` produces today. The pins and domain
  digests are unchanged (D4).

## Decisions

### Neutralise, never refuse

Every source in § *Measured behaviour* is neutralised, not detected. No closed
error code is added, and every published command keeps its closed error set
(D1). Caps, `RECORD_POLICY`, `PACKING_POLICY`, the committed bundle and
`ANCHOR_SHA256` are unchanged (D2). The full-shape tier proves the clean-run
bytes unchanged by comparing freshly derived payload members with the committed
ones. Settings
already neutral under the policy arguments also stay neutral inside the view,
because the view runs the same argv.

### Treatment of each source

| Source | Treatment |
|---|---|
| Repository `info/attributes` (Git directory and common directory) | Unreachable: the view is a different Git directory |
| In-tree `.gitattributes` (working tree, index, `HEAD`, nested) | Ignored everywhere: the view has no working tree or index, and `HEAD` is unborn (D3) |
| `GIT_ATTR_SOURCE`, `attr.tree` | Scrubbed from the environment; no configuration scope can carry `attr.tree` |
| `core.attributesFile` (any scope) | Unreachable: global configuration resolves under `HOME=<view>`, system configuration is off, and the repository and environment scopes are gone |
| Default user attributes (`$XDG_CONFIG_HOME` or `$HOME/.config/git/attributes`) | `XDG_CONFIG_HOME` is removed, and `HOME` is the view, which has no `.config` |
| System attributes file | `GIT_ATTR_NOSYSTEM=1` |
| System configuration (`$(prefix)/etc/gitconfig`; this host's has `credential.helper`) | `GIT_CONFIG_NOSYSTEM=1` |
| `diff.orderFile`, `diff.suppressBlankEmpty`, `core.bigFileThreshold`, `i18n.logOutputEncoding` and any other configuration key, at the repository, global, system or command-line environment scope | Unreachable: only built-in defaults and the policy's `-c` apply |
| `GIT_DIFF_OPTS`, `GIT_EXTERNAL_DIFF`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`/`KEY_*`/`VALUE_*`, the routing variables and every other `GIT_*` | Scrubbed |
| `diff.algorithm`, `diff.renames`, rename limits, external diff drivers and `textconv` | Neutral under the policy's explicit arguments (CORE design), and still neutral in the view |
| Replacement refs, grafts, shallow files, promisor fetch | The view has none of them. The history authority's existing refusals stay unchanged |

### In-tree `.gitattributes`

The record view ignores `.gitattributes` from every location (D3). Applying
the pinned file has no single answer for a range diff, because the base and
head trees can disagree, and for per-commit edge diffs each edge would need its
own source. The policy already disables what attributes mostly select:
`textconv` and external drivers. The clean-run publication had no
`.gitattributes` in any checkout (EV5), and this repository has never tracked
one. Ignoring the file therefore leaves the committed anchor unchanged.

### What stays outside the runner

These invocations do not shape a record, or they already authenticate their
own output, so they keep their current runners:

- history-authority object reads, which hash-check their own output
- `ls-tree` and `cat-file blob` for the EF-designer evidence. These read raw
  objects, and probes found them insensitive to attributes.
- the projection's scratch `read-tree`, `apply --cached` and `write-tree`, which
  were probed insensitive and are compared to the original trees
- the forecast's `diff --cached --name-only` emptiness check
- task-7 scratch construction
- signature verification
- the derivation's `rev-parse --git-common-dir` input check

### RP24 lifted

This spec is the next document to cite the determinism guarantee, and it lifts
RP24's narrowing (D5). REPLAY's guarantee, that two derivations on one host
configuration are byte-identical, now covers CORE's record view too. Two
derivations of the same pins are byte-identical on any host and any repository
configuration, for one Git version.

EVIDENCE's EV5 host check is therefore no longer needed for a future
publication. The REPLAY and EVIDENCE designs are point-in-time records, so they
are not rewritten. The living statement is the determinism paragraph in
`review_derivation`'s module docstring, which states the widened guarantee and
cites this issue.

## Test seams

Every hostile case runs with its own `HOME`, its own `XDG_CONFIG_HOME` and its
own `GIT_CONFIG_GLOBAL` file, and with `GIT_CONFIG_NOSYSTEM=1` in its process
environment, so no file from the host leaks in. A source command gets that
environment through its subprocess `env`. An in-process call gets it through
`unittest.mock.patch.dict(os.environ)`. Fixtures are built with the existing
`tests/retained_review_test_support.py` helpers.

1. **CORE records.** Use `actual_inputs` and `select_candidate` over a fixture
   range whose changes the hostile sources would visibly alter: a `.c` file, a
   blank context line, a rename, a large-enough file and a non-ASCII subject.
   The seam follows `tests/test_review_history.py` and the existing
   `HOSTILE_GIT_ENV` cases. Each hostile source in § *Treatment of each source*
   is one subtest, and each subtest makes two assertions:
   - **Control:** a raw `git -C repo diff` with the policy argv differs under
     that source. This is the red state the issue requires: before the change,
     records differ and nothing refuses.
   - **Isolation:** CORE's manifest and shards are byte-identical to the clean
     run.

   The `.gitattributes` subtests cover the working-tree file, the
   index-and-`HEAD` file, `GIT_ATTR_SOURCE` and `attr.tree`.

   One more case covers the sources that no test can make hostile, such as
   the host's read-only system configuration and system attributes file. Under
   the full hostile setup, it runs two commands through `record_git`:
   - `config --list --show-origin --show-scope`, which must list exactly the
     view's own `config` entries, each with `local` scope
   - `check-attr -a` over the fixture paths, which must print nothing

   Run raw against the source, the same two commands list the hostile entries.
   That is the case's control (D7).
2. **Retained derivation, portable tier.** Run `derive_bundle` over the
   portable fixtures in `tests/test_review_derivation.py` under one combined
   hostile environment, with `info/attributes`, repository configuration and a
   working-tree `.gitattributes` in the fixture repositories. The anchor and
   every member, `issue-121.json` among them, must equal the clean run's bytes.
3. **Source and built launcher parity.** `tests/test_agent_tools_launchers.py`
   runs `review-package` and `derive-review-feasibility-fixtures` from the
   built launchers and as `python -m` from source, both under the combined
   hostile environment. Their stdout and outputs must match the clean source
   run byte for byte.
4. **Full shape.** `tests/test_review_retained_full.py` gets one case. It
   derives once clean and once hostile from disposable
   `git clone --shared --no-checkout` clones of the root. The hostile run adds
   `info/attributes` to its clone, plus repository configuration and a hostile
   environment. Both runs use this checkout's package and tool commit, as the
   tier's `test_two_derivations_are_byte_identical` does. Two assertions follow:
   - The five files of the two runs are byte-identical. The anchors are equal
     too, because the tool commit is the same.
   - The three payload members, `issue-121.json` among them, are byte-identical
     to the committed bundle's members. Those members carry no tool identity, so
     this proves that clean-run bytes are unchanged on the real objects (D2).

   The anchor cannot equal `ANCHOR_SHA256`, because that anchor binds the
   reviewed tool commit's closure and this change edits the package.
   `test_committed_evidence_reproduces_with_the_reviewed_tool` keeps proving
   that committed anchor with the reviewed package. The root is compared before
   and after each run, as RP11 requires.

## Risks

- **Cost.** Each record call creates one directory and four small files, and
  makes one more `rev-parse`. That is about 14 ms on each of a few hundred
  calls per derivation. The REPLAY design sets no time cap.
- **The Git version still matters.** Built-in defaults can change between Git
  releases. The guarantee is therefore stated per Git version, as REPLAY's
  guarantee already was in practice.

## Out of scope

- New review features, changes to caps, to `RECORD_POLICY` or to
  `PACKING_POLICY`, and regeneration of the committed evidence.
- The history authority's existing defences: replacement refs, grafts, shallow
  files, partial clones and routing refusal. They stay as they are.
- Invocations listed in § *What stays outside the runner*.
- Rewriting the REPLAY or EVIDENCE designs.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Neutralise every record-shaping source by running record Git in a fresh, template-free bare view directory with an alternate to the source objects and a scrubbed environment; add no refusal and no closed code | Issue 255 allows either option. Probes show `info/attributes` cannot be overridden in place, and a refusal inside task-7 composition becomes a published `unsupported_composition` row | Override settings with `-c` and refuse a non-empty `info/attributes`: this enumerates keys, misses future ones, and turns a refusal into different published bytes. Scrubbing global configuration in place breaks `safe.directory` for repositories owned by another user |
| D2 | Keep the isolation outside `RECORD_POLICY`: the argv, policy digests, retained domains, anchor and `ANCHOR_SHA256` are unchanged | Probes show the view gives byte-identical clean output. The full-shape case proves it on the real objects, through payload-member equality with the committed bundle, because the anchor binds the tool closure | Add isolation flags to the policy's `git_config`: this changes `RECORD_POLICY_SHA256` and forces regenerating the committed evidence for no change in record content |
| D3 | In-tree `.gitattributes` is ignored everywhere | No single pinned source exists for range or edge diffs; the policy already disables `textconv` and external drivers; the EV5 clean run had none | Use the head tree as `--attr-source`: base and head can disagree, and a driver's configuration would still come from the host |
| D4 | One runner, `review_actual.record_git`, serves `git_diff`, a single `commit_subject` that replaces the two subject copies, and issue 100's recipe; nothing else moves | RP24 (one guard in CORE); the-bar DRY; issue 255 asks that derivation yield the same bytes, not refuse | Leave issue 100 on its own runner: it fails closed with `domain_mismatch`, so a hostile derivation refuses and never shows identical bytes |
| D5 | This spec lifts RP24's narrowing; the living statement is `review_derivation`'s determinism docstring; the REPLAY and EVIDENCE specs are left unedited | the-bar *Moves keep their history* (point-in-time records keep their text); issue 255 criterion 7 | Edit the REPLAY or EVIDENCE specs' text: this rewrites accepted records |
| D6 | Each hostile test pairs a control (raw source Git differs) with the isolation assertion, under a test-owned `HOME`, `XDG_CONFIG_HOME` and `GIT_CONFIG_GLOBAL` | the-bar *Tests that can fail*; issue 255 criteria 1 and 2 | Assert only equality: a hostile setting that never bit would pass vacuously |
| D7 | The record environment is minimal: `HOME=<view>`, `GIT_CONFIG_NOSYSTEM=1` and `GIT_ATTR_NOSYSTEM=1`, with every `GIT_*` variable and `XDG_CONFIG_HOME` dropped. Sources no test can make hostile are proven by an inventory: `config --list --show-origin` and `check-attr -a` run through `record_git` | the-bar *Tests that can fail*: a redundant guard is untested; this host's system `gitconfig` exists, so the inventory control bites | Also set `GIT_CONFIG_GLOBAL`: it duplicates `HOME=<view>`. Leave system sources unasserted: an unprovable neutralisation |
| D8 | One standard-library `tests/hostile_git_test_support.hostile_git_env` builds the combined hostile setup for every tier. The installed tier proves `review-package` parity (clean source = hostile source = hostile built) on its own fixture; derivation parity rides `RetainedLauncherTest`'s existing built run under environment-only hostility against its clean source run; the full-shape case compares one hostile derivation from a disposable clone with the class's clean bundle instead of deriving a second clean bundle from a clone | CP18 (the installed test imports no `agent_tools`, so it cannot build derivation fixtures); RP11 (the root is never written); each derivation over the real objects takes minutes, and the class bundle is already a clean derivation of the same objects by the same tool | A portable derivation in the installed tier: its fixtures need `agent_tools`. A second clean clone derivation per tier: one more long run that adds no coverage |
| D9 | The index-and-`HEAD` `.gitattributes` subtest asserts isolation only, with no biting control | Probes on Git 2.51.2 (spec § *Measured behaviour*, repeated in planning for a non-bare index/`HEAD` copy and a bare `HEAD`) show a tree-to-tree diff never reads them; the `GIT_ATTR_SOURCE` and `attr.tree` subtests show the same committed file bites when it is read | Also assert that raw Git ignores them: that pins a Git internal outside CORE and fails on a Git upgrade that CORE already survives |
| D10 | `commit_subject` raises `GenerationError("commit metadata is not UTF-8")` for both callers, so the projection's non-UTF-8 subject changes from a raw `UnicodeDecodeError` to that error | D4 (one home for subject reads); `review-feasibility` already catches both with exit 2, task-7 composition catches both, and issue 121's `_authenticated` now maps it to `evidence_unavailable` instead of a traceback; no retained subject is non-UTF-8, and the full-shape case proves the payload bytes unchanged | Keep each caller's own decoding: two copies of one rule that must change together |
