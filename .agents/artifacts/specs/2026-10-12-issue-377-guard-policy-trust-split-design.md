# Lifecycle guard: store-built trust, rechecked derived rows — issue 377

Design for https://github.com/fagenorn/nix-config/issues/377. "Issue 126 Dn"
cites the ledger of
`.agents/artifacts/specs/2026-10-12-issue-126-derived-guard-policy-design.md`;
a bare "Dn" cites this spec's ledger.

## Triage

Input: `contract_change` hit (second policy input; trusted members no longer read from the state file); `concurrency_or_persistence` hit (how the persisted state file is read and what a bad one means); `open_design_questions` hit (recheck mechanism, bad-file rule); `criteria_shape` hit (six criteria, the README one has no deterministic check). Paths: `home/common/claude-code/lifecycle_guard.py`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `tests/test_claude_permission_guard.py`, `python/agent_tools/guard_policy.py`, `python/README.md`, `tests/test_guard_policy.py`.
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

Since https://github.com/fagenorn/nix-config/pull/375 the registered hook reads
its whole policy from `~/.agents/state/guard/policy.json`. Any session running
as the user can rewrite that file with a file-writing tool, no guarded verb
involved, and so authorize any owner, declare any integration branch, or make
the guard execute any program as `git`, `gh` or `jq`. The guard checks the
file's schema, not its origin. Before #375 the policy was an immutable store
file. The owner decided on 2026-10-12 that this is hardened before the host is
switched: the trusted members come only from the store-built base policy, and
the writable file contributes derived rows and nothing else.

## Solution

The policy splits into two files with disjoint closed schemas. The **base
policy** (Nix store) holds the five trusted members. The **compiled policy**
(user state) holds `derived_repositories` and `derivation` only. The registered
wrapper names both, plus a store-built **row check** command. The guard loads
the base policy on every call and the compiled policy only when it judges a
repository-bound verb. A derived row is a claim, never a fact: before the guard
relies on one it runs the row check, which re-derives that one repository's row
from the fleet registry and the contract on `origin` with the compiler's own
proof, and the guard refuses unless the fresh row carries the same two branches.
A compiled policy that is missing, unreadable or outside its schema contributes
no row and blocks nothing the base policy alone authorizes.

## Requirements

- **R1.** No value of `authorized_owners`, `integration_bases`, `git_bin`,
  `gh_bin` or `jq_bin` reaches the guard from the compiled policy, and no
  program named by the compiled policy is ever executed.
- **R2.** A derived row authorizes its own repository only, and only after the
  row check confirmed it in this invocation.
- **R3.** A row for a repository that no registered project derives is refused
  at use, as is a row whose branches differ from the fresh derivation.
- **R4.** A bad compiled policy leaves every repository judged by the base
  policy alone; a bad base policy still blocks every Bash call.
- **R5.** On an untampered host the verdicts for `fagenorn/nix-config`,
  `elevenyellow/nodocom`, `fagenorn/arcwave` and other `fagenorn` repositories
  are those of #375.
- **R6.** The guard reaches a verdict inside its own deadline, short of the
  30-second hook timeout, whatever the network does.

## Decisions

### 1. Two schemas, one member each side (open questions 3 and 4)

| Member | Read from | Trust rule |
|---|---|---|
| `authorized_owners` | base policy | Store value only. |
| `integration_bases` | base policy | Store value only. A literal row is never removed or changed by the compiled policy. |
| `git_bin`, `gh_bin`, `jq_bin` | base policy | Store value only; the only programs the guard runs besides the row check. |
| `derived_repositories` | compiled policy | A candidate row per slug. Used only after the row check of section 3 confirms it. |
| `derivation` | compiled policy | Recorded for the reader; `null` or an object; not interpreted. |

The base policy is an object with exactly the five trusted members. The
compiled policy is an object with exactly `derived_repositories` and
`derivation`. The compiler stops writing the five trusted members (question 4),
and `derivation.schema_version` becomes 2. The base policy loses its empty
`derived_repositories` and null `derivation`, so no member exists in both files
and neither file is a valid instance of the other.

A compiled policy that carries any other key, a trusted member included, is
outside its schema (question 3: refused, not ignored and not compared). It then
falls under section 4's rule: it contributes no row. Nothing in it is read, so
a seven-member file left by a #375 build is treated the same way until the next
compile replaces it.

Row shape and name patterns are unchanged from issue 126: a slug key matching
the guard's slug pattern and `{default_branch, integration_branch, evidence}`.

### 2. Registration

The wrapper is
`python3 -I lifecycle_guard.py --base-policy <store base policy> --policy <compiled path> --derive-bin <store row check> "$@"`.
All three are required arguments. A later occurrence still replaces an earlier
one, which stays the test seam; the hook is registered argument-free.

The **row check** is a store script that puts the store `git`, `gh` and `ssh`
first on `PATH`, as `claude-guard-policy` does, and execs the `guard-policy`
launcher with `derive` and its own arguments. It is not installed on `PATH`.

The wrapper's build check runs the wrapper as registered, with no override, on
the harmless payload: the base policy must load, and the compiled path is never
opened because the payload has no repository-bound verb.

The existing `--git-bin`, `--gh-bin`, `--jq-bin` and
`--child-timeout-seconds` overrides stay, and `--derive-timeout-seconds`
(default 15) joins them.

### 3. The row check at use (open question 1)

**Command.** `guard-policy derive --repository <slug>` reads the registry, and
for each entry runs the two local `origin` reads of compile steps 1 and 2. Only
entries whose `origin` names `<slug>` go on to steps 3 to 10, through the same
`derive` function `compile` uses; step 11 and the name-shape check then apply
among them. It writes one line of JSON, `{schema_version, repository, outcome,
row, refused, cause}`:

| Outcome | Exit | Meaning |
|---|---|---|
| `derived` | 0 | Exactly one registered project proved `<slug>`; `row` is its row. |
| `refused` | 1 | No project did. `refused` lists each entry that named the slug with its reason code; it is empty when no entry names the slug. |
| `unavailable` | 2 | The registry does not validate, the platform manifest cannot load, or any unexpected failure; `cause` as in `compile`. |

It writes no file except the fetched objects and remote-tracking refs the
derivation always writes. Step 12 is not its job: it takes no base policy.

**Guard.** When a repository-bound verb is judged and the compiled policy holds
a row for the detected repository `S`, the guard, in this order:

1. refuses if `S` is a key of the base `integration_bases` (a repository cannot
   be both; the row is the suspect one);
2. applies the existing `origin/HEAD` check against the row's `default_branch`;
3. runs `<derive-bin> --repository S` with stdin at `/dev/null`, in its own
   process group, bounded by `--derive-timeout-seconds` and by the invocation
   deadline; on the bound the whole group is killed;
4. refuses unless the child exited 0 with a parseable report whose `outcome` is
   `derived` and whose `row` has the compiled row's `default_branch` and
   `integration_branch`. `evidence` is not compared: its commit moves with
   every push to the branch.

A refusal names the repository, the row check's reason code or the differing
branches, and `claude-guard-policy` as the repair. The check runs once per
invocation, when the context is built. A repository with a row is judged by the
row and never falls back to the owner literal when its check fails. A repository
with no row is judged by the base policy with no check and no network read, as
today.

The compiled policy keeps three jobs: it bounds the network check to
repositories the last compile proved, it carries the activation-time result an
operator reads, and it pins the branches, so a contract change on `origin`
refuses until a recompile instead of being adopted silently.

**Inputs.** The registry file, each naming entry's `origin` URLs, the contract
on the registered branch fetched from `origin` in this run, and the provider's
answer for `repos/S`. No ref already present is trusted.

**Bound and cost.** The guard records its start and gives itself an invocation
deadline of 27 seconds. Every child started once the context exists gets the
smaller of its own bound and the time left: 15 seconds for the row check,
`--child-timeout-seconds` (5) for the others. A child that hits its bound
refuses, as today, so the guard answers inside the hook timeout without relying
on what the harness does with a timed-out hook. Measured on the host on
2026-10-12: `git ls-remote origin` 1.9 s and `gh api repos/<slug>` 0.7 s. A
derivation is one listing, one fetch per branch read and one provider read, so
the expected cost is about 5 s for a single-branch project and about 7 s for
Nodo, on every repository-bound verb in a repository that has a row, nix-config
included. The full command was not timed.

**Unreachable `origin` or provider.** The check fails `fetch_failed` or
`provider_unproven` and the verb is refused. There is no fallback to a ref
already present or to the unchecked row. This costs no availability: push, PR
creation, merge and release creation each need the same remote or provider to
succeed.

**Environment and concurrency.** The row check inherits the guard's
environment; its `origin` and provider reads are `compile`'s own code, with
the same environment handling, so the hook needs no credential the repair
command does not. Two sessions whose verbs are judged at once may fetch
into the same registered root; a fetch that loses a ref lock fails
`fetch_failed` and the verb is refused, and running it again clears it. The
guard takes no lock of its own.

### 4. A bad compiled policy (open question 2)

A compiled policy that is missing, unreadable, not JSON or outside section 1's
schema contributes no row, whole file, with the reason kept. The guard does not
block: every repository is judged by the base policy alone. When a
repository-bound verb is then refused for standing authorization, the refusal
adds the reason and names `claude-guard-policy`. Commands with no
repository-bound verb never open the file.

This is safe because rows only add. The state "no row for any project" is
already reachable and accepted: an empty registry, or a compile in which every
project is refused, leaves exactly it. The one thing a row takes away is the
`origin/HEAD` consistency check of issue 126 D8 on a repository the owner
literal authorizes anyway, and that check compares the live branch with the
row, so without a row there is nothing to be inconsistent with. Emptying the
file therefore grants nothing: a derived-only repository loses authorization,
and an owner-literal repository is judged as an unregistered one.

It is also needed. Under the block-everything rule a scribbled file denies
every Bash call, the repair command included, until a human removes it from
another shell.

A base policy that is missing, unreadable or outside its schema still blocks
every Bash call with `invalid policy`, after the detaching-word check as today.
It is a store file the build check loaded, so a bad one is an installation
defect.

The activation step is unchanged except for its two messages, which now say
that registered projects have no derived row instead of that every Bash call is
blocked. It still removes the file when the compile refuses as a whole.

### 5. Compiler

`read_base` accepts exactly the five members. `compile` writes
`{derived_repositories, derivation}`. Step 12 stays: a project whose slug is a
base `integration_bases` key is refused `literal_conflict` and gets no row. The
literal row can no longer be withheld, because the compiled policy cannot
subtract from the base, so that repository keeps its literal integration branch
and each compile reports the conflict (D5).

`derive --repository` is a second subcommand of the same thin command module;
entry selection and the single-slug outcome are importable functions.

### 6. Residual

The guard catches the mistakes of a cooperating session. It is not a sandbox.
After this change, rewriting the compiled policy alone gains nothing. What
remains:

- **The registry is user-writable.** A session can add an entry. The row check
  then still demands that the repository's own branch on `origin` publishes a
  resolving contract that names that project id, that repository as tracker and
  as release target, and that the provider confirms the name. So a registry
  edit authorizes only a repository that already declares itself adopted and
  that the session could register with the registration command anyway. This is
  accepted.
- **Transport and tool configuration are user-writable.** `~/.ssh/config`, git
  configuration and the `gh` credential decide what `origin` and the provider
  answer. A session that rewrites them and the registry can forge a derivation.
  That is several deliberate edits to stores unrelated to the guard. Accepted,
  and out of scope.
- **`~/.claude/settings.json` is a writable copy.** Removing the hook removes
  the guard. Unchanged and out of scope.
- **Check to use.** The verb runs after the verdict; a remote that changes
  between them is not seen. Accepted.

### 7. Prose

`home/common/claude-code/README.md`: § Guard policy is rewritten for the two
schemas, the trust table, the row check with its cost and offline behaviour,
the bad-file rule and the residual above; the sentence that lists issue 126 D17
as open goes, and the D6 sentence becomes "rechecked at use, changed rows refuse
until the next compile". The roster sentence names the base `authorized_owners`
plus the confirmed derived rows. The first section's description of the wrapper
and of what blocks every call is corrected. `python/README.md` § guard-policy
gets the five-member base, the two-member output and the `derive` contract.
The guard paragraph of `docs/standards/agent-helpers.md` says the tool paths
come from the base policy and that the row check is run by its store path.
`CLAUDE.md` changes only if a sentence becomes false.

## Test seams

- **Guard command** (the built wrapper, `tests/test_claude_permission_guard.py`).
  Every invocation passes a fixture base policy, a fixture compiled policy and a
  fixture row check. The row check for the table is a stub executable in the
  style of the suite's `fake_gh`, answering from a per-test file. Existing rows
  keep their verdicts. New tampered-state rows:
  1. a compiled policy that adds `authorized_owners` with a new owner: a
     guarded verb in that owner's repository is refused (criterion 1);
  2. a compiled policy that sets `git_bin`, `gh_bin` and `jq_bin` to marker
     scripts: a merge in an owner-literal repository gets the untampered
     verdict and no marker is written (criterion 2);
  3. a well-formed row for an unregistered repository, row check `refused`:
     refused at use (criterion 3);
  4. Nodo's row with a forged `integration_branch`, row check answering `dev`:
     every repository-bound verb refused; the same for a forged row that gives
     an owner-literal repository an integration branch;
  5. a row whose slug is a base `integration_bases` key: refused;
  6. each bad-file shape (missing, directory, unreadable, not JSON, extra
     member, the seven-member shape, malformed row): `true` passes, an
     owner-literal verb gets the base-only verdict, a Nodo verb is refused
     naming the repair;
  7. the row check exiting 2, exiting 0 with garbage, or outliving a short
     `--derive-timeout-seconds`: refused;
  8. each bad base-policy shape still blocks `true`.
  Two pins: the wrapper text names the store base policy, the compiled path and
  a store row check; the built base policy has exactly the five members and the
  #375 literals.
- **Compiler command** (`python -m agent_tools.guard_policy`,
  `tests/test_guard_policy.py` over `tests/guard_policy_world.py`). `compile`
  cases move to the two-member output and five-member base. `derive` cases: a
  registered slug derives the row `compile` writes; an unregistered slug is
  `refused` with an empty list; a registered slug whose proof fails is `refused`
  with its code; two entries on one slug are `duplicate_repository`; a corrupt
  registry is `unavailable`; an entry naming another slug causes no fetch.
- **Round trip.** The guard suite drives the built guard with a compiled policy
  written by `compile` and the real `derive` over the same fixture world: the
  Nodo-shaped row is confirmed and its verb allowed, and a hand-added row for a
  repository the world does not register is refused by the real derivation.
- **Build.** `just build` runs the wrapper check as registered.

No test contacts a network remote or reads the host's registry or compiled
policy.

## Acceptance mapping

| Criterion | Proof |
|---|---|
| 1 | Guard row 1. |
| 2 | Guard row 2 (marker absent, verdict unchanged). |
| 3 | Guard row 3 and the round trip's forged row. |
| 4 | The existing guard table and Nodo cases with confirmed rows; the base-policy pin; the round trip's allowed verb. |
| 5 | Review of the rewritten § Guard policy against section 7; no deterministic check. |
| 6 | `just build` and `just agent-workflow-tests`. |

## Out of scope

- Making the fleet registry, git or ssh configuration tamper-proof.
- The writability of `~/.claude/settings.json`.
- Any change to which repositories an untampered host authorizes, and the
  `fagenorn` owner literal and Arcwave's row
  (https://github.com/fagenorn/nix-config/issues/129).
- Running `just switch`, and the issue 126 proof step.
- Caching a row check's result, or skipping the fetch when `origin` lists a
  commit already present; both are later optimisations of section 3's cost.
- Signing rows.
- Changes to the verb grammar, the protection demand or branch deletion.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Reverses issue 126 D1 and D17. Two files with disjoint closed schemas: the store base policy holds the five trusted members, the compiled policy holds `derived_repositories` and `derivation`; the compiler stops writing the trusted members and a compiled policy carrying one is outside its schema. | Owner decision of 2026-10-12 in the issue. The guard's closed-key-set precedent. The bar: no special case to hide a wrong shape. | Keeping the shared seven-member schema and ignoring five members of the state file: a file that states owners nobody reads, and an "ignore" path beside the closed schema. Refusing on mismatch with the base: a comparison that only tells a forger what to copy. |
| D2 | Narrows issue 126 D6. Each row is rechecked at use by re-deriving that one repository through the compiler's `derive`, run as a store child (`guard-policy derive`), and compared on its two branches; a differing or unprovable row refuses until a recompile. | The issue's first option. Issue 126 D9 and D11 (one branch rule, one contract reader). `agent-helpers.md`: the guard imports nothing from `agent_tools` and runs tools by store path. | A digest or signature over inputs the guard re-reads: every local input (registry, remote-tracking refs) is as writable as the file, a content check needs a second contract reader in the guard, and a signing key is readable by the same user. Using the fresh row and ignoring the stored branches: adopts a contract change silently and leaves the file meaningless. |
| D3 | The row check needs the network on every repository-bound verb in a repository with a row, nix-config included, with no stale fallback and no cache; a concurrent fetch that loses a ref lock refuses and is retried by hand, with no guard lock. | Issue 126 D2 (never fall back to the ref already present). The four verbs need the same remote. The bar: no special case. | Skipping the check for rows under an owner literal: such a row can still add an integration branch, which waives the protection demand. A result cache: another user-writable file. A guard-side lock: a further state file and a wait inside a bounded hook. |
| D4 | Reverses issue 126 D4's block-everything rule for the compiled policy, and R5 of that spec. A bad compiled policy contributes no row and blocks nothing; a bad base policy still blocks every call. | The issue asks for this when it is shown safe; section 4 shows rows only add and the empty state is already reachable. Issue 126's README: a refused project is judged by the literal rows alone. | Keeping block-everything: lets one file write deny every Bash call, the repair included. Per-row salvage of a malformed file: a partial read of a file already known to be wrong. |
| D5 | Narrows issue 126 D5 and D14. A literal `integration_bases` row is never withheld; `literal_conflict` still costs the project its row, and the guard refuses a repository that has both a literal row and a compiled row. | The owner decision: the compiled policy adds rows only, so it cannot subtract a store literal. No such overlap exists on the host. | A `withheld` member in the compiled policy: a third member and a way for the state file to change how a literal repository is judged. |
| D6 | The guard keeps an invocation deadline of 27 s; the row check gets 15 s in its own process group, killed whole on the bound. | The 30-second hook timeout; the merge arm already runs up to six 5-second children. What the harness does with a timed-out hook was not verified, so the guard must not depend on it. | Raising the hook timeout: a settings change that still leaves the sum of bounds above it. Bounding only the direct child: `git`, `ssh` and `gh` grandchildren would outlive the verdict. |
| D7 | The row check's path is a required wrapper argument, `--derive-bin`, not a base-policy member; the script pins `PATH` to the store tools. | The compiler reads the base policy and has no use for the path. `claude-guard-policy` is the precedent for the pinned `PATH`. | A sixth base-policy member: widens the schema both producers validate for a value one reader uses. |
| D8 | Test seams: the built guard with a stub row check for the adversarial table, the compiler command for `derive`, and one round trip joining the real two. | Issue 126 D10 and D15; the suite's `fake_gh` is the precedent for a stub at the process boundary. | The real derivation behind every table row: a fixture world per row for cases that assert the guard's reaction, not the proof. |
| D9 | No glossary or ADR is written; the terms **base policy**, **compiled policy**, **derived row** and **row check** are fixed in the guard README and this ledger is the decision record. | No context path is bound for this project; issue 126 D12 is the precedent. | Creating a context map or `adr/` directory: an unauthorized new knowledge surface. |
