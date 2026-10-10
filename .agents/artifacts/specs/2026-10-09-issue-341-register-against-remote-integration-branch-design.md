# Register against the remote integration branch, issue 341

https://github.com/fagenorn/nix-config/issues/341 (blocks
https://github.com/fagenorn/nix-config/issues/210).

## Problem

`adopt-project verify --register` answers every question it asks from the
registered root's own checkout. The contract and projection checks run the
resolver on the working tree. The inventory comes from the index. The evidence
record, migration map and introducing commit are read from `HEAD`. The #148 D19
ancestry gate runs `merge-base --is-ancestor <adopt> <integration_branch>`, and
git resolves a bare `dev` to the local `refs/heads/dev` first.

On the Nodo host, the primary checkout's local `dev` is 1 commit ahead of
`origin/dev` (unpushed user work) and 346 behind. After the adopt PR merges into
`origin/dev`, registration still fails: the adoption is not on the local
branch, and `HEAD` may not carry even the contract. The only way through is to
rewrite the user's branch, which agents must not do. The operator needs
registration to prove what the remote integration branch holds, and to leave
the local branch, working tree and untracked files untouched.

## Solution

`verify --register` stops reading the root's checkout. It fetches the
contract's integration branch from `origin`, pins the fetched commit, exports
that commit's tree into a temporary directory, and runs every conformance check
against that one commit. The registry entry is still `{project_id, root}` with
the real root (D18). Plain `verify` is unchanged and keeps its `HEAD`-based
answers (per D1).

Registration runs in this order. Every step either refuses with a closed code
(per D6) or hands the next step a pinned value:

1. **Remote.** `origin` must be configured (per D2).
2. **Remote default.** One `git ls-remote --symref origin HEAD 'refs/heads/*'`
   names the remote's default branch `D` and lists which branches exist, so a
   missing branch is a contract fact and never a fetch error (per D3, D4).
3. **Fetch and pin.** Fetch `D` into `refs/remotes/origin/D` and resolve it to
   a commit id `R` (per D4).
4. **Integration branch.** Export `R` (per D5) and run the resolver's `resolve`
   there. If the contract does not resolve, skip to step 5 at `R`: the report
   says the contract does not resolve, which is the truthful answer about the
   remote default. If it resolves, read `bindings.vcs.integration_branch` as
   `B`. When `B` equals `D`, the target is `R`. Otherwise fetch `B` once, pin
   `R'`, export it, resolve again, and require that the contract at `R'` also
   names `B`. A second mismatch, or a `B` absent from the step-2 listing,
   refuses (per D3).
5. **Checks at the pinned commit.** The six ordered checks run at the target
   commit (per D5). The report names the commit (per D8).
6. **Integration gate.** If the target commit's tree carries no evidence record,
   the request refuses `not_integrated` (per D7). Otherwise the existing result
   policy applies: `not_conformant` is reported on exit 0 with
   `registered: false`, and an `adopted`/`adopted_with_blockers` result goes on
   to registration.
7. **Register.** `register_project` keeps its inner checks against the pinned
   commit id, not a branch name: the adoption commit must be an ancestor of the
   target commit, and the contract must name the branch that was fetched (per
   D7). The locked registry write is unchanged.

The temporary export is removed whether the run succeeds or refuses.

## Decisions

**Module boundaries.** `adopt_inspection` gains the git primitives. Each one
takes an explicit revision rather than assuming `HEAD`:

- the blob of a path at a revision;
- the evidence-record candidates at a revision;
- the tree inventory at a revision, from `ls-tree -r -z`, returning the same
  `(path, object id)` pairs `tracked_inventory` does;
- the introducing commit of a path, walked from a revision;
- `ls-remote --symref` parsing, the fetch-and-pin step, and the archive export.

The existing `HEAD` helpers are kept as thin calls with `HEAD`, so `plan`,
`apply` and plain `verify` behave byte for byte as before. Network git calls run
with `GIT_TERMINAL_PROMPT=0`, so a credential prompt fails instead of hanging.
They keep the existing 300-second timeout.

**One verification core, two sources.** `verify_repository` takes a
*verification source*: the commit and ref label the report names, the directory
the resolver runs on, and the inventory to classify. Plain `verify` builds the
`HEAD` source: the working tree for the resolver, the index for the inventory,
`HEAD` for the records, which is today's behaviour. `--register` builds the
remote source from the steps above. The check order and the report shape do
not fork. `adopt_verify` owns the remote source and its context manager.
`command_verify` stays a thin shell: build the source, verify, apply the
integration gate, register, emit.

**Report shape (per D8).** The report gains `revision`:
`{"ref": "HEAD" | "refs/remotes/origin/<B>", "commit": "<40-hex>"}`.
`schema_version` moves to 2. `root` stays the real root in both modes.
`project_id` comes from the contract at the verified revision. Every other
member keeps its meaning.

**Capabilities and blockers.** Under `--register` the resolver runs on a cold
export. Capability verdicts therefore describe a fresh checkout of the remote
commit: an untracked or empty knowledge directory reads as missing. Both
`adopted` and `adopted_with_blockers` register, so this changes the label and
never the decision. Host-specific blockers in the user's own checkout remain
plain `verify`'s answer.

**Re-adoption.** When the remote carries an older adoption and a newer one is
still unmerged locally, registration verifies and registers against the remote
one. The entry is identity and location only (D18), so nothing stale is
persisted.

**Docs.** The `adopt_project` module docstring, the `adopt_verify` docstring,
the `--register` help text and the `blob_at_head`/`tracked_evidence_records`
docstrings are rewritten to describe the remote-revision rule. The #148 and
#149 specs are point-in-time records and are not edited.

## Test seams

Two seams, both following the existing suite:

1. **The CLI as a child process.** `python -m agent_tools.adopt_project verify
   --repo-root … [--register]` runs under the temporary `HOME`, as
   `VerifyTestCase` does today. `origin` is a local bare repository created by a
   new fixture helper, `publish(root, branches)`, which creates a bare repo whose
   `HEAD` points at `main`, re-points `origin` at it, and pushes. The fixtures
   still add `origin` as the GitHub URL, because plan identity derives from it
   (#148 D35), so the helper re-points it only after `plan`/`apply`. No network
   is needed.
2. **`register_project` imported directly**, for the inner ancestry and branch
   checks that no CLI path can reach (per D7). Tests import modules normally
   (docs/standards/agent-helpers.md rule 5).

Required cases:

- **AC1 (diverged):** adopt and push, then reset local `main` behind the
  adoption, commit unpushed user work, leave an untracked file and an unstaged
  edit, so the local tree has no contract. `--register` reports `registered:
  true`, `revision.ref == "refs/remotes/origin/main"`, and the remote's evidence
  record and adoption commit. The local `main` id, `git status --porcelain`, the
  tree snapshot and the untracked file's bytes are unchanged. The registry root
  is the local root. Plain `verify` on the same root stays `not_conformant`.
- **AC2 (not on remote):** the adoption is committed locally but not pushed, or
  sits only on the apply branch. `--register` refuses `not_integrated` and no
  registry file exists. This replaces today's apply-branch case, which keeps its
  plain-`verify` `adopted` assertion.
- **Refusals:** no `origin` gives `not_integrated`/`adopt.registration.no_remote`.
  An unreachable `origin` path gives `adopt_failure`/`adopt.git.remote_unreachable`.
- **Hop:** the remote default is `main`, the contract names `dev`, and `dev`
  carries the adoption, so registration verifies `refs/remotes/origin/dev`.
- **Inner check:** a `Verification` whose adoption commit is not an ancestor of
  the pinned commit refuses `not_integrated`. A contract naming another branch
  refuses `not_integrated`/`adopt.registration.integration_branch_unresolved`.
- The existing `RegistrationTest` successes (idempotence, duplicate id,
  ordering, concurrency, fleet view) publish first and keep their assertions.
  The report-shape test pins `revision` and `schema_version: 2`. Where a
  fixture's knowledge directories are empty, the fixture commits a placeholder
  file so a cold export still reports `adopted`.

## Out of scope

- `plan` and `apply`, and plain `verify` beyond the additive `revision` member.
- Rewriting, fast-forwarding or checking out any local branch, and any write to
  the working tree, index or untracked files. The only repository mutation is
  the fetch's update of `refs/remotes/origin/<branch>` and its objects.
- Shallow clones, whose introducing-commit derivation can stop at the shallow
  boundary. Plain `verify` has the same limit today.
- A configurable remote name, and remotes other than `origin`.
- New `ADOPT_ERROR_CODES` members.
- `export-ignore` attributes and out-of-tree symlinks, which `git archive` and
  `filter="data"` treat the same way in the existing cold-clone gate. Such a
  tree refuses `adopt.git.export_failed` or fails a check truthfully.
- Serializing two concurrent registrations of the same root: a lost ref-lock
  race refuses `adopt.git.fetch_failed`, and a rerun succeeds.
- Running Nodo's registration itself (#210).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "changes the observable semantics of the public `adopt-project verify --register` CLI: which ref ancestry and evidence are read from"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "registration persists to the user-scope fleet registry under a lock; the write path is unchanged but its precondition moves"}, "open_design_questions": {"value": "hit", "evidence": "how the remote default branch is named before the contract resolves, and how resolver checks run against a commit without touching the working tree, are open"}, "criteria_shape": {"value": "no", "evidence": "three acceptance criteria, each verified by a deterministic fixture test or the test recipe"}}, "paths": ["python/agent_tools/adopt_verify.py", "python/agent_tools/adopt_inspection.py", "python/agent_tools/adopt_project.py", "home/common/agent-skills/tests/test_adopt_verify.py"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Only `--register` moves to the remote revision. Plain `verify` keeps its working-tree, index and `HEAD` reads and its offline, read-only promise. | Issue default ("plain verify unchanged"). #149 B6 runs plain `verify` on the unmerged adoption branch and expects `adopted`. #148 R6.1. | Moving plain `verify` to the remote too: it breaks the pre-merge diagnostic and makes a read-only verb need the network. |
| D2 | The remote is `origin` by name. When it is absent, the request refuses. No flag. | Issue AC1 names `origin/<default>`. The bar's token economy. Every repo workflow pushes to `origin`. | #148 D35's "exactly one remote": it refuses a fork with both `origin` and `upstream`. A `--remote` flag: a parameter nobody needs yet. |
| D3 | `B` comes from the contract at the remote. Bootstrap at the remote's `HEAD` branch from `ls-remote --symref`, follow the contract's `integration_branch` at most once, and require the contract at `origin/B` to name `B`. | D26: the resolver is the only reader of policy. `bootstrap.md`: no project policy is defaulted. The issue's key subtlety: the local tree may lack the contract. | Local `refs/remotes/origin/HEAD`: unset after `git remote add` and can be stale. The local tree's contract: absent when diverged, and a second policy source. A CLI branch argument: duplicates contract policy. Requiring `B == D`: refuses gitflow repos. |
| D4 | Fetch with the explicit refspec `+refs/heads/B:refs/remotes/origin/B`, `--no-tags`, prompts off. Pin the resulting commit id, and pass that id, never a ref name, to every later read and to the ancestry check. Whether `B` exists is read from the step-2 `ls-remote` listing, never inferred from a failed fetch. | The issue asks for "the remote-tracking default branch (after a fetch)". A bare `dev` resolves to local `refs/heads/dev` first, which is today's bug. | `FETCH_HEAD`: shared and racy between concurrent fetches. A private ref namespace: hides the state the issue names. Skipping the fetch: verifies a stale remote-tracking ref. |
| D5 | The resolver checks run on a `git archive` export of the pinned commit, extracted with `tarfile` `filter="data"` into a temporary directory. Inventory, records, map and introducing commit are read from the pinned commit through git. Amends #148 D34's "at `HEAD`" for registration only. | Precedent: `adopt_apply`'s cold-clone gate exports a tree and runs `resolve`/`check-projections` on it. The AC1 rule that the local branch, working tree and untracked files are untouched. | A scratch `git worktree add --detach`: writes `.git/worktrees` admin into the user's repo, shows in `git worktree list`, and leaks on a crash. A temporary index with `checkout-index`: more machinery and no precedent. |
| D6 | No new error codes. Unprovable integration refuses `not_integrated`: `adopt.registration.no_remote`, `adopt.registration.remote_default_unknown`, `adopt.registration.integration_branch_unresolved`, `adopt.registration.not_integrated`. Operational faults refuse `adopt_failure`: `adopt.git.remote_unreachable` (ls-remote), `adopt.git.fetch_failed`, `adopt.git.export_failed`. | #148 D20 closes the ten-code set. `refuse(code, repair_id, pointer, message)` already separates causes by `repair_id`. | One code per cause: widens a closed set for distinctions the repair id already carries. |
| D7 | Under `--register`, a pinned commit whose tree carries no evidence record refuses `not_integrated` rather than reporting `not_conformant`. `register_project` keeps the #148 D19 ancestry check as the inner check, now against the pinned id, and adds a check that the contract names the fetched branch. Amends #148 D19's ref from the local branch to the pinned `origin/B` commit. | AC2 ("registration still fails"). #149 relies on the `not_integrated` refusal. The bar's defense in depth. A guard unreachable from the CLI needs a direct test (the bar, tests that can fail). | Reporting `not_conformant`: claims the project is non-conformant when its adoption is only unmerged. Dropping the ancestry check, since walking from `R` makes it hold by construction: removes the inner check of a trust boundary. |
| D8 | The report gains `revision {ref, commit}` in both modes, and `VERIFY_SCHEMA_VERSION` becomes 2. | The bar's truthful terminal states: under `--register` the checks describe a commit other than the root's `HEAD`. No consumer outside the tests reads the report. | No new member: a `not_conformant` report from the remote would send the operator to local files. Keeping schema 1: the pinned member set changes. |
| D9 | Test seams are the CLI child process with a local bare `origin` created by a `publish` helper, and `register_project` imported directly. Fixtures re-point `origin` only after `plan`/`apply`. | The existing `VerifyTestCase` and helpers. agent-helpers.md rule 5. #148 D35 derives identity from the GitHub URL fixture. | A mocked git or resolver: asserts calls rather than behaviour. A network remote: non-hermetic. |
| D10 | The HEAD-only readers become revision readers in place (`blob_at`, `evidence_records_at`, `introducing_commit(root, revision, relative)`), with no `HEAD` wrappers left behind. Plain `verify` pins `HEAD` to a commit id once and reads every record at that id. Amends the Decisions sentence that keeps the `HEAD` helpers as thin calls. | Only `adopt_verify` calls the three helpers (`plan`/`apply` never do), so nothing else can change. The bar's YAGNI. The report's `revision.commit` (D8) must name the commit the records were read from. | Keeping `HEAD` wrappers: dead code with no caller. Reading `HEAD` by name after pinning: a commit landing mid-run makes the report name one commit and read another. |
| D11 | The fetch runs `git fetch --quiet --no-tags --no-write-fetch-head --no-auto-maintenance --no-recurse-submodules origin +refs/heads/B:refs/remotes/origin/B` with `GIT_TERMINAL_PROMPT=0`. The diverged-branch test asserts `.git/FETCH_HEAD` is absent afterwards. | The spec's Out of scope: the only repository mutation is `refs/remotes/origin/B` and its objects. D4 already rejects `FETCH_HEAD` as an input. | Plain `git fetch`: writes `FETCH_HEAD`, may start auto-maintenance and recurse into submodules, each a mutation the spec excludes. |
| D12 | Amends D11: the fetch also passes `--refmap=`, and a fixture adds a `remote.origin.fetch` mapping onto a local branch and asserts that branch does not move. | Phase-5 Codex review PR-01: with a command-line refspec, git still applies configured `remote.origin.fetch` mappings opportunistically, which could update or refuse on a local branch, breaking the untouched-local-branch criterion. | Rely on the explicit refspec alone: a non-default fetch mapping would still move a user ref. |
