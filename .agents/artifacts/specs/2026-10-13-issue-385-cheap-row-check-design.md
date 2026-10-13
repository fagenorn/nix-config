# Guard: a row check cheap enough for Nodo — issue 385

Design for https://github.com/fagenorn/nix-config/issues/385 (parent
https://github.com/fagenorn/nix-config/issues/126, follows
https://github.com/fagenorn/nix-config/issues/377). "Issue 126 Dn" and "issue
377 Dn" cite the ledgers of
`.agents/artifacts/specs/2026-10-12-issue-126-derived-guard-policy-design.md`
and `.agents/artifacts/specs/2026-10-12-issue-377-guard-policy-trust-split-design.md`;
a bare "Dn" cites this spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "the guard-to-row-check interface and the documented guard-policy derive contract (python/README.md) change"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "the check writes remote-tracking refs and fetched objects in the registered checkout and may run git and gh children concurrently"}, "open_design_questions": {"value": "hit", "evidence": "the issue leaves the design (cheap re-derivation vs cheap proof) to the spec"}, "criteria_shape": {"value": "hit", "evidence": "AC1 is a repeated wall-clock measurement on this host, which no deterministic code check verifies"}}, "paths": ["python/agent_tools/guard_policy.py", "python/agent_tools/adopt_verify.py", "home/common/claude-code/lifecycle_guard.py", "home/common/claude-code/default.nix", "home/common/claude-code/README.md", "python/README.md", "tests/test_guard_policy.py", "tests/guard_policy_world.py", "tests/test_claude_permission_guard.py"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

With #126 and #377 installed, the compiled policy holds a confirmed-at-compile
row for `elevenyellow/nodocom` (default `main`, integration `dev`), yet the
guard refuses every Nodo PR into `dev`: the use-time row check
(`claude-guard-row-check --repository elevenyellow/nodocom`) takes 13.5–14.9 s
and the guard bounds it at `min(15 s, time left in 27 s)`, so it times out.
Recompiling cannot help. The repository #126 was built for cannot use its row.

Where the time goes (one profiled run of `guard-policy derive` on the host,
2026-10-13, plus component timings): Nodo's registry entry carries a branch
override, so the derivation lists `origin` (2.1–2.3 s), fetches `main`, exports
its whole tree with `git archive` and extracts it with Python's `tarfile`
(about 19 000 members), resolves it (it does not resolve), fetches `dev`,
exports and extracts that tree too, lists the whole `dev` tree with `ls-tree
-r`, and finally asks `gh api` (0.8 s). Two fetches cost about 2 s each, the
two extractions plus the scratch removal cost several seconds of pure local
work, and a two-branch fetch costs about the same 2.1 s as a one-branch one:
the cost of a network read is the ssh connection, not the refs. Importing the
package costs 0.07 s.

The issue's remark that the check "probes the remotes of every registered
project" is a misreading: steps 1 and 2 run for every entry, but they are two
local `git remote get-url` reads each; only entries naming the slug reach the
network. That part is not changed.

## Solution

Keep the use-time check what #377 made it, a full re-derivation of the one
repository by the compiler's own proof, and make that proof cheap. Two changes
inside the shared read of `origin`, and none in the guard:

1. **Read only what the listing does not prove present.** The one `ls-remote`
   already returns every branch's commit id. A branch whose listed commit is
   already in the checkout's object store is read at that id with no fetch;
   only a listed commit that is missing is fetched, with today's pinned-fetch
   spelling.
2. **Materialize only what the resolver reads.** Instead of exporting the whole
   tree, the derivation writes into its scratch directory the contract blob and
   the blobs of each declared projection's source and target, the only files a
   resolution reads that can change its verdict, and runs the resolver there.
   No `ls-tree -r` inventory is taken.

Both changes apply to `compile` and `derive` alike, since they share `prove`;
`adopt-project --register` keeps its full read unchanged. Steady-state cost for
Nodo becomes one listing, two small local reads per branch, the resolver and
one provider read: about 3.3 s. After a push to a branch the check reads, one
fetch is added (about 2.1 s).

## Decisions

### 1. Direction: cheap re-derivation, not a cheap proof (open question 1)

A cheap proof compared against the compiled row, such as the contract blob id
at the integration head, would compare against evidence written in the
user-writable compiled policy. A forger copies the live blob id into a row
whose branches are forged; the blob id passes and the branches are never read.
Making that safe needs the contract's content read, which is the derivation.
#377 D2 already rejected digests over writable inputs on the same ground. So
the guard keeps running `derive` and comparing the two branches, and the guard
file, its bound (`--derive-timeout-seconds` 15, 27 s deadline) and the
adversarial table do not change (D1).

### 2. One listing; fetch only missing commits

`RemoteHeads` gains the listed commit id of every branch it names, from the
same `ls-remote --symref origin HEAD refs/heads/*` (no new network read).
A new pin operation for a listed branch: when `git cat-file -e <id>^{commit}`
succeeds in the registered root, the branch is pinned to the listed id and
nothing is written; otherwise `fetch_pinned` runs exactly as today and its
read-back commit is the pin. A listing that fails still refuses as today: no
ref already present is consulted, and freshness comes from this run's listing.

This narrows issue 126 D2 ("fetch at each compile") without its rejected
alternative: the rejected source was the *remote-tracking ref*, which any
local ref write moves; here the id comes from the live listing and the object
is named by its hash. It also adds no trust: `git fetch` itself transfers
nothing when the wanted commit is already present, so today's derivation
already reads the local object store for that commit (D2).

A branch read without a fetch leaves its remote-tracking ref as it is. The
row's `evidence.source.ref` keeps its spelling, `refs/remotes/origin/<branch>`,
as the name of the branch read, and `evidence.source.commit` is the pinned id;
evidence is not compared by the guard (issue 377 D2). The written-file
contract becomes "at most the remote-tracking refs of the branches fetched and
the fetched objects" (D3).

A present commit whose tree objects then cannot be read (a damaged or partial
object store) refuses through the export (`fetch_failed`), never falls back to
a fetch or to another commit. The checkout's object store is user-writable like
the registry: a session that plants a loose object under the id `origin` lists
forges the read, as it already can before a fetch that finds the object
present. The guard README's residual list names it beside transport
configuration.

### 3. Materialize the resolver's reads

The resolver reads, under the root it is given: the contract file; for each
declared projection its source and its target (`validate_projections`, which
refuses on a missing source, a missing or stale target); and, for capability
states only, knowledge paths, the worktree parent and command paths. With no
required capabilities, capability states never refuse, and the proof reads
none of them (it reads `project.id`, `bindings.tracker`, `bindings.vcs` and
`release.targets`, and compiles profiles from the contract alone).

`resolve_project` gains one public function naming the relative paths a
resolution reads beyond the contract: each projection entry's `source` and
`target` that is a safe relative path, taken from a parsed contract of any
shape without raising (a malformed entry is left out; validation refuses that
contract before any projection file is read). The resolver thus stays the only
reader of contract policy (issue 126 D11) and the one home of that list.

A new package module, `agent_tools.contract_export`, owns the sparse export:
given a root, a commit and a fresh destination, it reads the contract path at
the commit; when it is a regular blob it writes it, parses it with
`resolve_project.load_contract`, asks for the paths above and writes each one
that is a regular blob (mode `100644` or `100755`) at the commit, creating its
parent directories. Anything else at a path (absent, a tree, a symlink, a
submodule) is left absent, so the resolver refuses as it does for a missing
file: a symlinked projection file is refused rather than followed (D4). A
contract that does not parse is written as read and the resolver refuses it.
Blob reads go through one `git cat-file --batch` child. A git failure refuses
`adopt.git.export_failed` as `export_commit` does.

The snapshot built on a sparse root has meaningless capability states; the
proof never reads them, and no snapshot is persisted (issue 126 D11). On
2026-10-13 every registered project's projection files are regular blobs, and
Nodo's `main` contract refuses on the sparse root with the same
`invalid_contract` (`contract.workflow.member_unexpected`) as on a full export,
so Nodo still takes its override to `dev`.

### 4. One branch-selection rule, two readers

`adopt_verify.remote_source` keeps its signature and its selection rule (the
default branch, the one hop, the `--integration-branch` operand rules) and
gains one keyword parameter, the **reader**: a small frozen value bundling how
a branch is pinned, how a pinned commit is exported, and whether an inventory
is taken. The default reader is today's (`fetch_pinned`, `export_commit`,
`tree_inventory`), so `adopt-project` calls it unchanged and its observable
behaviour, writes and reports stay identical. `guard_policy.prove` passes the
cheap reader (section 2 pin, section 3 export, no inventory). A source read
without an inventory carries `inventory=None`, so a verification that tried to
read it would fail loud instead of passing an empty inventory (D5).

`adopt_verify` still never imports the resolver (issue 148 D26): the cheap
export lives in `contract_export`, which `guard_policy` hands in.

### 5. Shared by compile; no concurrency, no cache

`compile` uses the same `prove`, so the row the check derives is still the row
`compile` writes and the compile gets faster too (D6). The provider read stays
sequential at step 10 and the guard's bounds stay as they are; a result cache
remains rejected (issue 377 D3).

### 6. Timing target and evidence (open question 4)

**Target.** On this host (`mbp`), the store `claude-guard-row-check
--repository elevenyellow/nodocom`, with `GITHUB_TOKEN` and `GH_TOKEN` unset,
the registered checkout `/Users/anis/Projects/nodocom` and network as found:
median **at most 5 s** over 10 consecutive runs, and no run above **10 s**.
Every run must report `outcome` `derived` with `default_branch` `main` and
`integration_branch` `dev`. The fetch path is not forced; when a run fetched
(a remote-tracking ref moved during the series), that run is named in the
evidence. The expected figures are about 3.3 s steady and about 5.4 s with one
fetch, inside the 15 s bound either way.

**Evidence.** Each acceptance criterion is evidenced as follows, and the
measured numbers go into the guard README's cost paragraph in place of the
#377 estimate:

| Criterion | Evidence |
|---|---|
| AC1 | The 10-run series above, against the row check built by `just build` (the wrapper's `--derive-bin` path in the built generation), each run's wall time and outcome recorded in the PR. |
| AC2 | A dry adjudication: the built guard wrapper (from the same build) fed a `PreToolUse` JSON payload on stdin, `tool_name` `Bash`, `tool_input.command` `unset GITHUB_TOKEN && gh pr create --repo elevenyellow/nodocom --base dev --head <branch> --title "x" --body "y"`, `cwd` an existing Nodo worktree whose `<branch>` is neither `main` nor `dev`, with the host's registry and compiled policy (a missing Nodo row is first restored with the installed `claude-guard-policy`). Expected: the allow verdict. No command is executed and no worktree is created. |
| AC3 | The guard suite's existing tampered-state rows (forged row, unregistered repository, mismatched branches, base-key overlap, each bad file) and the round trip, unchanged and green, plus the new compiler cases below. |
| AC4 | `just build` and `just agent-workflow-tests`. |

### 7. Prose

`home/common/claude-code/README.md` § Guard policy: the cost paragraph gets the
read described here and the AC1 measurements in place of the #377 estimate,
and the residual list gains the object store. `python/README.md`
§ guard-policy: the shared read (listing, fetch only when missing, sparse
export, no inventory) and the narrowed write statement for `compile` and
`derive`. The `adopt_verify` module text names the reader parameter. `CLAUDE.md`
changes only if a sentence becomes false.

## Test seams

All existing seams, no new kind (issue 126 D10, issue 377 D8):

- **Compiler command** (`python -m agent_tools.guard_policy derive|compile`
  over `tests/guard_policy_world.py`, a local bare `origin`). New cases:
  1. a branch whose listed commit is already present derives with no fetch:
     its remote-tracking ref is left where the test put it;
  2. a branch pushed after the checkout last fetched is fetched: its
     remote-tracking ref names the new commit, and the row's commit is it;
  3. resolver equivalence on the sparse export: worlds whose contract on the
     read branch has a stale projection target, a missing projection target, a
     missing projection source, a symlinked projection target, an unparseable
     contract and no contract are each refused with the same reason code
     (`contract_unresolved` or `branch_unresolved` with an override) as the
     full export gives, and a world with in-sync nested projection files
     derives;
  4. the Nodo-shaped world (override, default contract unresolved) derives its
     row through both pin paths.
  Existing `derive` and `compile` cases stay green with unchanged reports.
- **Module function** `contract_export` driven on a fixture repository for
  the mode rules (regular blob written, executable bit irrelevant, symlink,
  tree and absent left absent), the one direct test seam of this change, in
  the style of `target_profiles`'s hand-built case (issue 126 D15).
- **Adopt suites** unchanged and green: the default reader is the proof that
  `--register` did not change.
- **Built guard** suite and its round trip unchanged; it drives the real
  `derive` over the fixture world, so the cheap reader is in the round trip.

No test measures time or contacts a network remote; the timing target is
acceptance evidence on the host, not a unit test (D7).

## Out of scope

- Any change to `lifecycle_guard.py`, its bounds, its deadline or the hook
  timeout; the trust split, the base policy and the compiled-policy schema.
- `adopt-project --register` behaviour, reports and writes.
- SSH connection multiplexing (`ControlMaster`) or any transport configuration.
- Running `gh` concurrently with git, caching row-check results, or signing
  rows.
- Changing steps 1 and 2 for non-matching entries (they are local reads).
- Running `just switch` and the issue 126 end-to-end proof beyond AC2's dry
  adjudication.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The use-time check stays a full re-derivation by the compiler's own proof, compared on the two branches; the guard file and its bounds are untouched, and the speed comes from the shared read of `origin`. | Issue 377 D2 (re-derive, compare branches; digests over writable inputs rejected). The issue's security property. Profile: the time is in the read, not the guard. | A cheap proof compared to the row's `evidence` (contract blob id): evidence sits in the writable compiled policy, so a forged row copies the live id and its branches are never read. Raising `--derive-timeout-seconds`: no room under the 27 s deadline and 30 s hook. |
| D2 | Narrows issue 126 D2: the commit id comes from this run's `ls-remote` and a commit already in the object store is read at that id without a fetch; only missing commits are fetched, by `fetch_pinned` unchanged. | Issue 377's out-of-scope line names this exact later optimisation. `git fetch` transfers nothing for a present commit, so the local object store is already trusted today. Measured: every network read costs about 2.1 s. | Always fetching: two extra round trips for Nodo. Reading the remote-tracking ref: the stale source issue 126 D2 rejected. Dropping the listing and taking the default from `gh api`: a second source for the default branch beside `origin/HEAD`. |
| D3 | A branch read without a fetch leaves its remote-tracking ref untouched; evidence keeps `refs/remotes/origin/<branch>` as the branch's name with the listed commit. | Smaller and more reversible; no ref lock, so two sessions no longer contend in the steady state. Evidence is not compared (issue 377 D2). | `git update-ref` to the listed id: a write, a lock and a new contention refusal for a label. A new evidence schema: churn in a file nothing interprets. |
| D4 | Sparse export of exactly the contract plus each projection's source and target, regular blobs only; the path list is a `resolve_project` function and the exporter is a new module `agent_tools.contract_export`. Symlinked or non-blob files are left absent and so refused. | The resolver's own reads (`compose_snapshot`): only those files can change its verdict without required capabilities. Issue 126 D11 and issue 148 D26 (one contract reader; adopt modules never import the resolver). The bar: split when the second concern arrives; fail closed. | A full export with native git (`checkout-index`): still about 1 s per 19 000-file tree plus removal. A resolver mode reading from a commit: rewrites every resolver read. Following symlinks: a second resolution of in-tree links for an edge case nobody declares. |
| D5 | `remote_source` keeps one selection rule and gains a reader parameter whose default is today's read; the guard passes the cheap reader; a source without an inventory carries `None`. | Issue 126 D9 and D13 (branch selection's one home is `remote_source`). The issue: adopt behaviour must not change. The bar: DRY, fail loud. | A second selection rule in `guard_policy`: two copies of the hop and operand rules. Changing `remote_source` for everyone: changes `--register`. An empty inventory: a verification would pass the unclassified-path check falsely. |
| D6 | `compile` shares the cheap read through `prove` (open question 5). | Issue 377 D2: the row check is the compiler's own proof; one proof keeps `derive`'s row equal to `compile`'s. | A cheap `derive` with a full `compile`: two proofs that can disagree on a project. |
| D7 | AC1 is a host measurement: median at most 5 s over 10 consecutive runs, none above 10 s, every run `derived` with `main`/`dev`; AC2 is a dry adjudication by the built wrapper. Tests stay deterministic and assert writes and verdicts, never time. | The issue's suggested target and AC wording. The bar: tests that can fail for one reason; verify before claiming done. | A timing unit test: flaky on a shared host. Forcing the fetch path in the series: needs deleting objects from the user's checkout. |
| D8 | No glossary or ADR is written; the guard README's cost paragraph and `python/README.md` § guard-policy carry the changed contract. | `paths.context` is `[]`; issue 126 D12 and issue 377 D9 precedent. | A new knowledge surface: unauthorized. |
