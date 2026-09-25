# Issue 181: build-delivery resolution — refusal detail and resolution root

## Problem

`workflow-state build-delivery --kind contract` resolves project policy
itself. #171's D27 made that deliberate: the build module does no I/O, and a
resolver refusal is a builder refusal. #100's D10 records it as the one
sanctioned helper-internal resolution. #100's integration review found two gaps
in that path.

1. **Refusal detail is lost.** `resolve-project` refuses with exit 2 and a
   closed error document on stdout, `{"error":{"code","repair_id","violations"
   [,"reason_code"]}}`. The builder turns that into the stderr line
   `workflow-state: resolve-project refused: <code>`, which drops `repair_id` and
   the ordered `violations`. Every workflow skill tells its owner to report those
   exactly. Through this one path, an owner can only report a code. The detail an
   operator needs to repair the contract (which pointer, which message, which
   repair id) is gone.
2. **The resolution root is implicit.** Callers pass
   `--repo-root <ledger_repo_root>`. `resolve-project` treats that argument as
   the root as given, with no walk-up. An owner's retained `ResolvedProject`
   comes from its own checkout, which is usually the issue worktree. Suppose a
   branch edits `.agents/project.json`, for example to change
   `bindings.vcs.integration_branch`. The sealed contract then carries the ledger
   root's value while the owner's snapshot carries the branch's value. Neither the
   help text nor any document says which root the contract was sealed from.

The issue's acceptance criteria are numbered here for reference:

- **AC1:** a resolver refusal still exits 2 with empty stdout, and its
  diagnostic preserves `error.code`, `repair_id` and ordered `violations` exactly.
- **AC2:** the resolution root is stated in help text or contract, and either
  matches the owner's root or the builder refuses when the two roots' policy
  differs.
- **AC3:** tests cover a refusal with a non-empty `violations` list, and a
  worktree whose `.agents/project.json` differs from the primary checkout's.

When is a contract built? Only at acquisition: direct `--auto` acquisition,
`orchestrate-issues` control, or explicit durable init-run. The build always
runs from the ledger root. For a first attempt it names a *reserved candidate*
worktree that does not exist yet. For a retry or a new run it names the
*recorded* worktree, which exists and can carry a branch edit. Once a contract
is installed, the ledger's contract governs.

## Solution

The builder keeps its single sealed resolution at `--repo-root` and says so.
Two changes close the gaps.

- **Preserve the refusal.** When the resolver refuses (exit 2 with a well-formed
  error document), the builder still exits 2 with empty stdout. Its one stderr
  line carries the resolver's error document in canonical JSON, byte for byte
  what the resolver printed, behind a fixed prefix that names which root refused.
  Other resolver outcomes, meaning a non-conforming exit or output or a timeout,
  get distinct diagnostics that carry the resolver's exit status and output. They
  are never passed off as a refusal.
- **State the root, and refuse divergence.** `--kind contract` seals policy
  resolved at `--repo-root`, the ledger repository root. Help text, `CLAUDE.md`
  and the two contract-building skills say so. When the input `worktree`
  already exists on disk, the builder resolves there too and compares the seven
  policy members the contract seals. If any member differs, or the worktree
  cannot be resolved, the build refuses with exit 2 and empty stdout. If the
  worktree is absent, as a reserved candidate is, there is nothing to compare, and
  the contract is sealed from `--repo-root` alone.

"The owner's resolution root" here means the contract's `worktree`. Custody
binds every post-acquisition owner to that exact path, and each owner resolves
at the checkout it operates in. So the input `worktree` is the owner's root, not
a stand-in for it. The owner's root never supplies sealed policy. It can only
block a build whose sealed policy it would contradict. This meets the issue's
acceptance arm "the builder refuses when the two roots' policy differs"
(per D3, D4).

## Decisions

### 1. Resolver outcome handling (per D1, D2)

The workflow-state command runs the resolver as it does today, with the same
argv location, `resolve --repo-root <root>` and a 60-second timeout. It then
classifies the outcome for a *root label*, which is one of the two closed tokens
`repo-root` or `worktree`:

| Resolver outcome | Builder stderr line (after `workflow-state: `) |
|---|---|
| exit 0, stdout one JSON object | success: the object is the snapshot handed on |
| exit 2, stdout a well-formed refusal document | `resolve-project refused at <label>: <document>` |
| any other exit or stdout (non-zero exit that is not a well-formed refusal; exit 0 whose stdout is not a JSON object) | `resolve-project failed at <label>: {"exit":<int>,"stderr":"<text>","stdout":"<text>"}` |
| no exit within the timeout | `resolve-project timed out at <label>` |

- **Well-formed refusal document.** This is a JSON object with exactly one
  member, `error`. `error` holds `code` (string), `repair_id` (string) and
  `violations`, plus `reason_code` (string) and nothing else. `violations` is a
  list whose items are objects with exactly `pointer` and `message`, both
  strings. The builder checks this structure. It does not re-check which codes
  exist or the rule that `reason_code` appears only with `unsupported_schema`:
  the resolver's `emit_error` owns those, and restating them would give one
  contract two homes.
- **`<document>`** is the whole parsed refusal document re-serialized in the
  canonical form (sorted keys, compact separators, ASCII escaping, no
  non-finite numbers). The resolver emits that same form, so the line's JSON
  suffix is byte-identical to the resolver's stdout minus its trailing newline.
  The document is always one line. The label is the only variable token before
  it, and the root paths are not in it, because the caller supplied both.
  Callers read everything after the fixed prefix as the resolver's document.
- **`failed`** carries the resolver's exit status plus its stdout and stderr,
  each decoded as UTF-8 with replacement, as JSON strings in one compact object.
  That is the failure body the-bar requires on this path.
- Every row still raises the command's `WorkflowError`, so the existing `main`
  keeps the exit-2, empty-stdout, one-line-stderr contract. Only the message text
  changes.

### 2. The contract build sequence (per D3, D4, D5)

For `--kind contract` only, the command does the following:

1. Load the input and resolve `--repo-root` under label `repo-root` (§1).
2. Build through the runtime facade exactly as today. The builder validates the
   closed input: an absolute, normalized `worktree` whose final component matches
   the issue's branch pattern. It then derives the contract from the `repo-root`
   snapshot. A malformed input refuses here, before any second resolver run.
3. If something exists at the validated `worktree` path (checked with `lexists`,
   so a dangling symlink counts as present and fails closed), resolve that path
   under label `worktree` (§1). Then call the builder's pure sealed-policy
   comparison with both snapshots. A worktree refusal, failure or timeout is a
   builder refusal.
4. Print the contract pair only after every check has passed.

Nothing else changes. The other six kinds still resolve nothing, and the command
still takes no lock, reads no ledger, reads no clock and writes nothing.

### 3. Sealed-policy comparison (per D4, D5)

The build module gains one authoritative home for the sealed members: an
ordered table of seven entries, each a (provenance key, snapshot path, type)
triple. The snapshot paths are `project.id`,
`bindings.tracker.kind`, `bindings.tracker.repo_slug`,
`bindings.vcs.branch_pattern`, `bindings.vcs.worktree.prefix`,
`bindings.vcs.integration_branch` and `bindings.vcs.merge.delete_branch`, plus a
pure accessor that extracts them from a snapshot through the existing
missing/mistyped refusals. Contract derivation, the provenance digest's
`policy` object and the comparison all read that table, so the member list stops
being written out twice.

`DeliveryBuilder` gains a pure method, `check_worktree_policy(repo_root_policy,
worktree_policy)`, and `DeliveryRuntime` forwards it under the same name. It
returns nothing when the seven values are equal, compared by value and type.
Otherwise it refuses, naming the differing snapshot paths in table order:
`worktree policy differs from repo-root policy: bindings.vcs.integration_branch,
bindings.vcs.merge.delete_branch`. A member missing or mistyped in the worktree
snapshot refuses with the accessor's message prefixed by `worktree `.

The command wraps the call exactly as it wraps `build_delivery`, so any exception
becomes `workflow-state: build-delivery refused: <reason>` with exit 2. The
builder interface version stays 1: the builder and the runtime ship as one
unit, and the standards retire version handshakes for new code.

The comparison is root-independent. None of the seven values is a path, so the
worktree's differently rooted `bindings.paths` never count. A branch edit to
anything the contract does not seal, such as review commands, orchestration
limits or knowledge paths, does not block the build. That policy governs the
owner's own phases through its own retained snapshot, which is the design #100
intends.

The provenance digest stays exactly as #171 defined it, same members and same
bytes. A contract built for an existing, agreeing worktree is therefore
byte-identical to one built with the worktree absent.

### 4. Worktree states (per D4, D6)

| State of the input `worktree` path | Outcome |
|---|---|
| absent (reserved candidate) | sealed from `repo-root` only, with no second resolution |
| present and resolves, sealed members equal | built; output identical to the absent case |
| present and resolves, a sealed member differs | exit 2, empty stdout, `build-delivery refused: worktree policy differs …` |
| present, resolver refuses (`not_onboarded`, `invalid_contract`, `invalid_projection`, …) | exit 2, empty stdout, `resolve-project refused at worktree: <document>` |
| present, resolver fails or times out | exit 2, empty stdout, the `failed` / `timed out` line at `worktree` |

Divergence can start on either side. The branch may edit a sealed member. The
integration branch may change a sealed member after the branch was cut and
before the branch syncs. Or the ledger root's checkout may itself be stale,
because what gets sealed is that root's checked-out tree, not the remote
integration branch. All three refuse the same way. The repair is to bring the
two trees into agreement: sync the branch, land or revert the edit, or update
the ledger root's checkout. It is never to pick one value over the other.

A first attempt's contract is built for an absent candidate, and nothing
re-checks it later. If that branch then edits a sealed member, the installed
contract still governs its delivery, as the lifecycle already states. A retry
or new run for that issue is built for the recorded worktree and refuses until
the trees agree. That is deliberate: it is exactly the divergence the issue asks
the builder to refuse. It is written down here, not coded around.

### 5. Where the root is stated (per D7)

- **Help text, the authoritative statement.** The `build-delivery` subparser
  gains a description, and `--repo-root` gains help. `--kind contract` resolves
  project policy with `resolve-project` at `--repo-root`, the ledger repository
  root, and seals that policy. When the input `worktree` exists, it also
  resolves there and refuses if any sealed policy member differs. A resolver
  refusal is relayed on stderr as the resolver's error document.
- **`CLAUDE.md`.** The "Delivery objects are built" sentence names that source:
  policy resolved at `--repo-root`, cross-checked against an existing worktree.
  It also says a refusal relays the resolver's document on stderr.
- **from-issue direct acquisition and orchestrate-issues' per-issue contract
  rule.** Each gets one clause stating the root and the cross-check. Each
  builder-refusal sentence changes to "report the builder's stderr line
  verbatim", because it now carries the resolver's `error.code`, `repair_id` and
  ordered `violations` exactly. from-issue's explicit durable acquisition
  already defers to orchestrate's rule and changes no further. The pinned
  sanctioned-exception sentence stays as it is. ship-issue and ship-handoff build
  no contract and change nothing.
- **Point-in-time specs.** #171 and #100 are not edited. This ledger refines
  #171 D27 and closes the two gaps #100 D10 names.

## Test seams

1. **Builder CLI subprocess seam.** This is the existing `BuilderHarness` in the
   delivery workflow suite: a synthetic resolvable project, `workflow-state
   build-delivery` run as a subprocess, and exit status, stdout and stderr
   asserted. It is the highest seam and already carries the refusal table.
   - *AC1, refusal detail.* Use a `--repo-root` contract with two schema
     violations, for example `bindings.tracker.repo_slug` removed and
     `bindings.vcs.merge.delete_branch` mistyped. This yields `invalid_contract`
     with two ordered violations. Assert exit 2, empty stdout, and stderr equal to
     `workflow-state: resolve-project refused at repo-root: ` plus the stdout the
     resolver itself prints for the same root and `HOME`, with its newline
     stripped. The expected bytes come from running the resolver directly, never
     from a literal, so the test fails only if the builder alters the document.
     The parsed suffix's `violations` must have length 2 and the resolver's order.
   - *AC3, divergent worktree.* Create the harness worktree as a real directory
     inside the project root's `.worktrees/`, holding a resolvable project
     layout (contract, instruction source and current projections, as the
     suite's project-root helper lays out, so the worktree resolver refuses for no
     unintended reason) whose contract changes one sealed member (for example
     `bindings.vcs.integration_branch`). Assert a refusal naming that member, with
     exit 2 and empty stdout.
   - *Agreeing worktree.* Use an identical worktree project. Assert the output is
     byte-identical to the absent-worktree build.
   - *Unsealed difference.* Use a worktree project that differs only in an
     unsealed member (for example `bindings.workflow.orchestration.max_parallel`).
     Assert the build succeeds.
   - *Worktree refusal.* Use an existing worktree directory with no contract.
     Assert stderr is `resolve-project refused at worktree: ` plus the resolver's
     own `not_onboarded` document.
2. **workflow-state module seam, for the paths no real resolver produces.**
   The workflow-state suite already loads the script with `load_source_module`
   and patches with `mock.patch.object`. Feed the outcome classifier a crafted
   non-conforming completed process (exit 1 with non-JSON stdout, and exit 0 with
   a non-object) and assert the `failed` line's exact JSON. Patch the subprocess
   call to time out and assert the `timed out` line.
3. **CLI help seam, AC2.** `workflow-state build-delivery --help`, compared
   with whitespace normalized because argparse re-wraps text, names
   `--repo-root` as the contract's resolution root and names the worktree
   cross-check.
4. **Skill contract seam.** The workflow skill contract suite pins the new
   from-issue and orchestrate-issues clauses (the root statement and the verbatim
   stderr relay) in the same way it pins the sanctioned-exception sentence.

Verification stays with the resolved `nix-build` and `agent-workflow-tests`
command IDs.

## Out of scope

- Making `build-delivery` consume the caller's retained snapshot or a
  caller-named policy root. #100 D10 rejected rewriting the lifecycle core.
- Any change to `resolve-project`, its error document or its root discovery.
- The other six `build-delivery` kinds, which resolve nothing.
- Re-checking an installed contract against later branch edits, whether in
  ship-issue, in an owner phase or in control. Once installed, the contract
  governs.
- Changing `delivery-contract/v1`, for example sealing the resolution root
  into provenance.
- Moving `workflow-state` or the build module into the `agent_tools` package.
  That belongs to their cluster's own move.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A resolver refusal (exit 2 with a structurally well-formed `{"error":…}` document) becomes one stderr line, `workflow-state: resolve-project refused at <repo-root\|worktree>: ` followed by the document re-serialized canonically. That JSON is byte-identical to the resolver's stdout minus its newline. Stdout stays empty. The builder checks structure only, never the code set or the `reason_code` position. | AC1. #100's rule to preserve `error.code`, `repair_id` and ordered `violations` exactly. #171 §1 (exit 2, empty stdout). The resolver's `emit_error` is the one home of the code rules (the-bar DRY). | Printing the document on stdout, which breaks the empty-stdout contract. A prose rendering of violations, which is lossy and unparseable. Forwarding raw multi-line output, which makes the diagnostic's boundary ambiguous. Re-validating resolver codes, which gives them a second home. |
| D2 | A non-conforming resolver outcome is reported as `resolve-project failed at <label>: {"exit","stderr","stdout"}`, and a timeout as `resolve-project timed out at <label>`. Neither is presented as a refusal. | the-bar: truthful terminal states, and the log stream is the debugger (log the failure body). Phase-0 open question 1. | Keeping the bare exit code, which drops the only pointer to the fault. Synthesizing a refusal document, which forges resolver output. |
| D3 | `--kind contract` seals only the policy resolved at `--repo-root`, the ledger repository root, and help text, `CLAUDE.md` and the contract-building skills say so. A worktree never supplies sealed policy. It can only veto a build. | #171 §1 and D27 (resolve at `--repo-root`). #100 D10 (one sanctioned internal resolution). from-issue: once installed, the ledger's contract governs. The policy that governs delivery belongs to the integration branch, not to a branch's own proposed edit. | Resolving at the worktree or owner root when present, which lets an unreviewed branch retarget its own delivery and makes sealed policy depend on attempt timing. A `--policy-root` argument, which adds a failure site that absent candidates cannot fill. Consuming the retained snapshot, which #100 D10 rejected. Recording the root in the contract, which changes `delivery-contract/v1`. |
| D4 | The owner's resolution root is the contract's `worktree`, since custody binds owners to it. When anything exists at that validated path (`lexists`), the builder resolves it too and compares the seven sealed members by value and type. A difference refuses and names the members in table order. A worktree refusal, failure or timeout is a builder refusal. An absent path skips the check. An agreeing worktree yields byte-identical output. | AC2's refuse-on-divergence arm. Bootstrap: no policy is defaulted, and non-path bindings are returned exactly as authored, so the seven members do not depend on the root. The-bar fail loud. Only the seven members reach the contract. | Comparing whole snapshots, where paths always differ and changes the contract never carries would still block. Skipping the check when the worktree refuses, which quietly defaults the comparison. Treating an absent candidate as an error, which would make every first attempt fail. |
| D5 | Build first and cross-check second, so the second resolver run only targets a path the builder has already vetted. The sealed-member table has one home in the build module, used by derivation, the provenance digest and the comparison. The comparison is a pure `DeliveryBuilder` method forwarded by `DeliveryRuntime`, and it is wrapped as a refusal. workflow-state keeps all the I/O. The builder interface version stays 1. | #171 D27 (no I/O in the build module). The-bar DRY and single responsibility. The agent-helpers intent that the command is a thin shell with policy in importable functions. agent-helpers rule 3 retires version handshakes, and the pair ships as one unit. | Resolving before validation, which runs the resolver at an unvetted path and duplicates validation. Comparing in workflow-state, which makes a second copy of the member list. A resolver callback injected into the builder, which puts I/O inside the pure seam. Comparing two built contracts' digests, which is obscure and cannot name members. |
| D6 | Accepted limitation: a first attempt's contract, built for an absent candidate, is never re-checked. Divergence from either side (a branch edit, an unsynced integration-branch change, or a stale ledger-root checkout, since the root's checked-out tree is what gets sealed) refuses a retry or new run until the trees agree. This is documented, not coded around. | The issue explicitly allows refuse-on-divergence. from-issue: once installed, the contract governs. The suggested scope boundary for this issue. | Adding re-checks in ship-issue, owner phases or control, which widens the lifecycle core beyond this issue. Exempting sealed-member edits from the veto, which recreates the gap. |
| D7 | Help text is the authoritative root statement. `CLAUDE.md` and the from-issue and orchestrate-issues contract steps state the root and relay the stderr line verbatim. The pinned sanctioned-exception sentence, ship-issue and ship-handoff are unchanged. The #171 and #100 specs are not edited, and this ledger refines #171 D27. | AC2 ("help text or contract"). The-bar: point-in-time records keep their text, and DRY (one home, the others link to it). | Editing accepted specs. Adding the clause to skills that build no contract. Stating the root only in prose, with no help text. |
| D8 | Tests run at the builder CLI subprocess seam, taking their expected refusal bytes from running the real resolver on the same root and `HOME` rather than from literals. They cover a refusal with two ordered violations and a real worktree directory under `.worktrees/`. A module seam (`load_source_module` and `mock.patch.object`) covers only the non-conforming and timeout paths. Help and skill-contract pins cover AC2. | AC1 and AC3. The-bar: tests that can fail, with fixtures shaped like production output. Existing `BuilderHarness` and workflow-state module-load precedent. | Mocking the resolver for the refusal case, which tests the mock rather than the resolver's bytes. A single-violation fixture, which cannot catch reordering. Hard-coded expected JSON, which a resolver wording change would break for a reason unrelated to the builder. |
| D9 | Extends D8 (plan). `check_worktree_policy` is also pinned directly at the existing runtime-facade seam (`test_workflow_delivery.py`, loaded with `runpy`). That covers its multi-member message order and its `worktree `-prefixed missing and mistyped refusals, which no real resolver can produce, because the resolver requires all seven members with their types. The CLI seam also gains an `unsupported_schema` refusal (the `reason_code` branch of D1's structure check) and a dangling-symlink worktree (D4's `lexists`). A digest check there also recomputes the provenance digest from the seven authored members, pinning §3's unchanged bytes across the table refactor. | The-bar: tests that can fail, and a guard with no test is untested; defense in depth keeps the accessor on the worktree snapshot. A planning probe showed the resolver refusing a dangling-symlink root as `not_onboarded`, and a `schema_version` 2 contract as `unsupported_schema` with a `reason_code`. | Leaving the worktree accessor path untested because no resolver fixture reaches it. Deleting that guard, which leaves the build module trusting its caller's snapshot. Driving it through workflow-state with a patched resolver, which tests the patch rather than the method. |
| D10 | Phase-5 review: keep D4's `os.path.lexists` presence test unchanged. A path whose ancestor the builder cannot search reads as absent and is sealed without a cross-check. This is an accepted limitation, and the docstring still describes presence as `lexists`. | D4. The owner process runs with the builder's permissions, so a worktree path the builder cannot `lstat` is one the owner cannot adopt or create either, and Phase 1 fails at that path before any delivery. The reviewer rated the finding low confidence. | Using `os.lstat` and refusing on every error except `FileNotFoundError`. That widens D4 for a case that never yields a usable worktree. |
